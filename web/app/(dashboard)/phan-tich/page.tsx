import Link from "next/link";
import { PageHeader, EmptyState, QueryErrorState } from "@/components/ui";
import { AnalysisBoard, type SignalResult, type FactorCorr, type FactorPair, type FactorCorrSplit } from "@/components/analysis-board";
import { getLatestVersionRuns, resolveReviewVersion } from "@/lib/dashboard-data";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { ScoringVersionSelect } from "@/components/scoring-version-select";

export const dynamic = "force-dynamic";

const RESULT_COLUMNS = "pred_id, scoring_version, symbol, signal_date, snap_time, decision, score_trade, confidence, t0_close, ret_1d, ret_3d, ret_5d, ret_10d, mfe_pct, mae_pct, own_entry, own_tp1, own_tp2, own_stop, std_outcome, std_days, std3_outcome, own_outcome, own_days";
const INITIAL_LIMIT = 2000;

type Props = { searchParams: Promise<{ version?: string; symbol?: string; window?: string }> };

export default async function PhanTichPage({ searchParams }: Props) {
  const params = await searchParams;
  const metadata = await getLatestVersionRuns("analysis-metadata");
  const currentVersion = resolveReviewVersion(params.version, metadata.byVersion);
  const versionDates = Object.fromEntries(Object.entries(metadata.versionDates).filter(([, value]) => !!value)) as Record<string, string>;
  const symbol = String(params.symbol ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10);
  const dataClient = createCachedPublicClient("analysis", currentVersion);
  const coverageResponse = await dataClient.from("v4_dashboard_version_summary")
    .select("scoring_version, signal_date_min, signal_date_max")
    .in("scoring_version", Object.keys(versionDates));
  const coverage = (coverageResponse.data ?? []) as Array<{ scoring_version: string; signal_date_min: string | null; signal_date_max: string | null }>;
  const commonStart = coverage.map((row) => row.signal_date_min).filter((value): value is string => !!value).sort().at(-1) ?? null;
  const commonEnd = coverage.map((row) => row.signal_date_max).filter((value): value is string => !!value).sort()[0] ?? null;
  const commonAvailable = !!commonStart && !!commonEnd && commonStart <= commonEnd;
  const useCommonWindow = params.window === "common" && commonAvailable;

  let resultsQuery = dataClient
    .from("v4_signal_analysis_dashboard")
    .select(RESULT_COLUMNS)
    .eq("scoring_version", currentVersion)
    .order("signal_date", { ascending: false })
    .order("symbol", { ascending: true })
    .limit(symbol ? 1000 : INITIAL_LIMIT);
  if (symbol) resultsQuery = resultsQuery.eq("symbol", symbol);
  if (useCommonWindow) resultsQuery = resultsQuery.gte("signal_date", commonStart!).lte("signal_date", commonEnd!);

  const [resultsResponse, diagnosticsResponse] = await Promise.all([
    resultsQuery,
    dataClient
      .from("v4_analysis_diagnostics_snapshot")
      .select("kind, dim, bucket, factor, factor_b, grp, n, corr_ret5, corr_win, corr, computed_at")
      .eq("scoring_version", currentVersion),
  ]);
  // Timeline is the primary dataset. Diagnostics are read from the daily snapshot,
  // never from the expensive correlation views during a page request.
  const hasError = metadata.error || resultsResponse.error;
  const hasOptionalError = diagnosticsResponse.error;
  const rows = (resultsResponse.data ?? []) as SignalResult[];
  const diagnostics = (diagnosticsResponse.data ?? []) as Array<Record<string, unknown>>;
  const corr = diagnostics.filter((row) => row.kind === "factor").map((row) => ({
    factor: String(row.factor), grp: row.grp == null ? null : String(row.grp), n: Number(row.n),
    corr_ret5: row.corr_ret5 as number | string | null, corr_win: row.corr_win as number | string | null,
  })) as FactorCorr[];
  const pairs = diagnostics.filter((row) => row.kind === "pair" && row.factor_b).map((row) => ({
    fa: String(row.factor), fb: String(row.factor_b), n: Number(row.n), corr: row.corr as number | string | null,
  })) as FactorPair[];
  const split = diagnostics.filter((row) => row.kind === "split").map((row) => ({
    dim: String(row.dim), bucket: String(row.bucket), factor: String(row.factor),
    grp: row.grp == null ? null : String(row.grp), n: Number(row.n),
    corr_ret5: row.corr_ret5 as number | string | null, corr_win: row.corr_win as number | string | null,
  })) as FactorCorrSplit[];

  return (
    <>
      <PageHeader title="Phân tích tín hiệu" desc="Tín hiệu BUY/STRONG BUY mới nhất và kết quả đã đủ phiên, cùng các biến đầu vào liên quan." />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <ScoringVersionSelect currentVersion={currentVersion} versions={Object.keys(versionDates)} route="/phan-tich" dates={versionDates} />
        {commonAvailable ? <div className="inline-flex min-h-10 items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-1 text-xs"><Link href={`/phan-tich?version=${encodeURIComponent(currentVersion)}`} className={`rounded-md px-2.5 py-1.5 ${!useCommonWindow ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-muted)]"}`}>Toàn lịch sử</Link><Link href={`/phan-tich?version=${encodeURIComponent(currentVersion)}&window=common`} className={`rounded-md px-2.5 py-1.5 ${useCommonWindow ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-muted)]"}`} title={`${commonStart} → ${commonEnd}`}>Cùng cửa sổ</Link></div> : null}
        <form method="get" action="/phan-tich" className="flex min-h-10 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm">
          <input type="hidden" name="version" value={currentVersion} />
          {useCommonWindow ? <input type="hidden" name="window" value="common" /> : null}
          <label htmlFor="analysis-symbol" className="text-[var(--color-muted)]">Tra mã ngoài tập đang tải</label>
          <input id="analysis-symbol" name="symbol" defaultValue={symbol} placeholder="VD: FPT" maxLength={10} className="w-24 rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 uppercase" />
          <button className="rounded bg-[var(--color-accent)] px-3 py-1 text-white">Tìm</button>
        </form>
      </div>
      {hasError ? <QueryErrorState hint="Một hoặc nhiều nguồn dữ liệu phân tích không tải được. Không hiển thị kết quả không đầy đủ." /> : !rows.length ? (
        <EmptyState title={symbol ? `Chưa có tín hiệu cho ${symbol}` : "Chưa có tín hiệu BUY/STRONG BUY để phân tích"} hint={`Scoring ${currentVersion} chưa có dữ liệu phù hợp.`} />
      ) : (
        <>
          {hasOptionalError ? (
            <p className="mb-2 rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-[var(--color-muted)]">
              Dữ liệu tín hiệu đã tải đầy đủ. Một phần thống kê tương quan đang tạm thời không khả dụng nên được ẩn thay vì làm trống toàn bộ tab.
            </p>
          ) : null}
          {useCommonWindow ? <p className="mb-2 text-[11px] text-[var(--color-muted)]">Đang so sánh trên cửa sổ chung {commonStart} → {commonEnd}; các version dùng cùng phạm vi ngày.</p> : null}
          {!symbol && rows.length === INITIAL_LIMIT ? <p className="mb-2 text-xs text-[var(--color-muted)]">Đang hiển thị {INITIAL_LIMIT.toLocaleString("vi-VN")} dòng gần nhất. Dùng ô tìm toàn bộ lịch sử để tra một mã cũ.</p> : null}
          <AnalysisBoard results={rows} corr={corr} pairs={pairs} split={split} />
        </>
      )}
    </>
  );
}
