import Link from "next/link";
import { PageHeader, EmptyState, QueryErrorState } from "@/components/ui";
import { SignalsTable, type SignalRow } from "@/components/signals-table";
import { HistoryFilters } from "@/components/history-filters";
import { getLatestVersionRuns, resolveReviewVersion } from "@/lib/dashboard-data";
import { createClient } from "@/lib/supabase/server";
import { getCompanyName } from "@/lib/company-names";

export const dynamic = "force-dynamic";
const PAGE_SIZE = 50;

type Params = { date?: string; symbol?: string; decision?: string; version?: string; page?: string };

export default async function HistoryPage({ searchParams }: { searchParams: Promise<Params> }) {
  const sp = await searchParams;
  const metadata = await getLatestVersionRuns("history-metadata");
  const currentVersion = resolveReviewVersion(sp.version, metadata.byVersion);
  const versionDates = Object.fromEntries(Object.entries(metadata.versionDates).filter(([, value]) => !!value)) as Record<string, string>;
  const page = Math.max(1, parseInt(sp.page ?? "1", 10) || 1);
  const from = (page - 1) * PAGE_SIZE;

  const supabase = await createClient();
  let query = supabase
    .from("v4_signals")
    .select("id, symbol, decision, score_trade, regime, signal_date, snap_time, scoring_version, breakdown", { count: "exact" })
    .eq("scoring_version", currentVersion)
    .order("signal_date", { ascending: false })
    .order("snap_time", { ascending: false })
    .range(from, from + PAGE_SIZE - 1);
  if (sp.date) query = query.eq("signal_date", sp.date);
  if (sp.symbol) query = query.eq("symbol", sp.symbol.toUpperCase().trim());
  if (sp.decision) query = query.eq("decision", sp.decision);

  const { data, count, error } = await query;
  const baseRows = (data ?? []) as SignalRow[];
  const predIds = baseRows.map((row) => String((row.breakdown ?? {}).pred_id ?? "")).filter(Boolean);
  const outcomesResponse = predIds.length
    ? await supabase.from("v4_outcomes").select("pred_id, ret_3d, ret_5d, ret_10d, mfe_pct, mae_pct")
        .eq("scoring_version", currentVersion).eq("lens", "trade").in("pred_id", predIds)
    : { data: [], error: null };
  const outcomeMap = new Map((outcomesResponse.data ?? []).map((outcome) => [String(outcome.pred_id), outcome]));
  const rows = baseRows.map((row) => ({
    ...row,
    companyName: getCompanyName(row.symbol),
    outcome: outcomeMap.get(String((row.breakdown ?? {}).pred_id ?? "")) ?? null,
  }));
  const total = count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const qs = (nextPage: number) => {
    const params = new URLSearchParams({ version: currentVersion, page: String(nextPage) });
    if (sp.date) params.set("date", sp.date);
    if (sp.symbol) params.set("symbol", sp.symbol);
    if (sp.decision) params.set("decision", sp.decision);
    return `/history?${params.toString()}`;
  };

  return (
    <>
      <PageHeader title="Lịch sử" desc="Tra cứu tín hiệu theo scoring version / ngày / mã / decision." />
      <HistoryFilters currentVersion={currentVersion} versions={Object.keys(versionDates)} dates={versionDates} />
      {metadata.error || error || outcomesResponse.error ? <QueryErrorState hint="Không thể tải lịch sử tín hiệu từ Supabase. Bộ lọc hiện tại chưa được áp dụng." /> : rows.length ? (
        <>
          <SignalsTable rows={rows} showDate />
          <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-muted)]">
            <span>{total.toLocaleString("vi-VN")} tín hiệu · {currentVersion} · trang {page}/{totalPages}</span>
            <div className="flex gap-2">
              {page > 1 ? <Link href={qs(page - 1)} className="inline-flex min-h-[40px] items-center rounded-md border border-[var(--color-border)] px-4 py-2">← Trước</Link> : null}
              {page < totalPages ? <Link href={qs(page + 1)} className="inline-flex min-h-[40px] items-center rounded-md border border-[var(--color-border)] px-4 py-2">Sau →</Link> : null}
            </div>
          </div>
        </>
      ) : <EmptyState title="Không có tín hiệu khớp" hint={`Không có dữ liệu ${currentVersion} phù hợp với bộ lọc hiện tại.`} />}
    </>
  );
}
