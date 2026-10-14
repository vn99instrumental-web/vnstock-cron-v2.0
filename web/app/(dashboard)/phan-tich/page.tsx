import { PageHeader, EmptyState, QueryErrorState } from "@/components/ui";
import { AnalysisBoard, type SignalResult, type FactorCorr, type FactorPair, type FactorCorrSplit } from "@/components/analysis-board";
import { getLatestVersionRuns, resolveReviewVersion } from "@/lib/dashboard-data";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { ScoringVersionSelect } from "@/components/scoring-version-select";

export const dynamic = "force-dynamic";

const RESULT_COLUMNS = "pred_id, scoring_version, symbol, signal_date, snap_time, decision, confidence, t0_close, ret_1d, ret_3d, ret_5d, ret_10d, mfe_pct, mae_pct, own_entry, own_tp1, own_tp2, own_stop, std_outcome, std_days, std3_outcome, own_outcome, own_days";
const INITIAL_LIMIT = 2000;

type Props = { searchParams: Promise<{ version?: string; symbol?: string }> };

export default async function PhanTichPage({ searchParams }: Props) {
  const params = await searchParams;
  const metadata = await getLatestVersionRuns("analysis-metadata");
  const currentVersion = resolveReviewVersion(params.version, metadata.byVersion);
  const versionDates = Object.fromEntries(Object.entries(metadata.versionDates).filter(([, value]) => !!value)) as Record<string, string>;
  const symbol = String(params.symbol ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10);
  const dataClient = createCachedPublicClient("analysis", currentVersion);

  let resultsQuery = dataClient
    .from("v4_signal_analysis_feed")
    .select(RESULT_COLUMNS)
    .eq("scoring_version", currentVersion)
    .order("signal_date", { ascending: false })
    .order("symbol", { ascending: true })
    .limit(symbol ? 1000 : INITIAL_LIMIT);
  if (symbol) resultsQuery = resultsQuery.eq("symbol", symbol);

  const [resultsResponse, corrResponse, pairsResponse, splitResponse] = await Promise.all([
    resultsQuery,
    dataClient.from("v4_hit_factor_corr").select("*").eq("scoring_version", currentVersion),
    dataClient.from("v4_factor_pair_corr").select("*").eq("scoring_version", currentVersion),
    dataClient.from("v4_hit_factor_corr_split").select("*").eq("scoring_version", currentVersion),
  ]);
  // Timeline is the primary dataset. Correlation views are optional diagnostics and
  // must not blank the whole page when one expensive aggregate times out.
  const hasError = metadata.error || resultsResponse.error;
  const hasOptionalError = corrResponse.error || pairsResponse.error || splitResponse.error;
  const rows = (resultsResponse.data ?? []) as SignalResult[];

  return (
    <>
      <PageHeader title="Phân tích tín hiệu" desc="Tín hiệu BUY/STRONG BUY mới nhất và kết quả đã đủ phiên, cùng các biến đầu vào liên quan." />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <ScoringVersionSelect currentVersion={currentVersion} versions={Object.keys(versionDates)} route="/phan-tich" dates={versionDates} />
        <form method="get" action="/phan-tich" className="flex min-h-10 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm">
          <input type="hidden" name="version" value={currentVersion} />
          <label htmlFor="analysis-symbol" className="text-[var(--color-muted)]">Tìm toàn bộ lịch sử</label>
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
          {!symbol && rows.length === INITIAL_LIMIT ? <p className="mb-2 text-xs text-[var(--color-muted)]">Đang hiển thị {INITIAL_LIMIT.toLocaleString("vi-VN")} dòng gần nhất. Dùng ô tìm toàn bộ lịch sử để tra một mã cũ.</p> : null}
          <AnalysisBoard results={rows} corr={(corrResponse.data ?? []) as FactorCorr[]} pairs={(pairsResponse.data ?? []) as FactorPair[]} split={(splitResponse.data ?? []) as FactorCorrSplit[]} />
        </>
      )}
    </>
  );
}
