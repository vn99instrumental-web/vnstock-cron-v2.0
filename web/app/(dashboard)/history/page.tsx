import Link from "next/link";
import { PageHeader, EmptyState } from "@/components/ui";
import { SignalsTable, type SignalRow } from "@/components/signals-table";
import { HistoryFilters } from "@/components/history-filters";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

export default async function HistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string; symbol?: string; decision?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const page = Math.max(1, parseInt(sp.page ?? "1", 10) || 1);
  const from = (page - 1) * PAGE_SIZE;

  const supabase = await createClient();
  let q = supabase
    .from("v4_signals")
    .select("id, symbol, decision, score_trade, regime, signal_date, snap_time, scoring_version, breakdown", {
      count: "exact",
    })
    .order("signal_date", { ascending: false })
    .order("snap_time", { ascending: false })
    .range(from, from + PAGE_SIZE - 1);

  if (sp.date) q = q.eq("signal_date", sp.date);
  if (sp.symbol) q = q.eq("symbol", sp.symbol.toUpperCase());
  if (sp.decision) q = q.eq("decision", sp.decision);

  const { data, count } = await q;
  const rows = (data ?? []) as SignalRow[];
  const total = count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const qs = (p: number) => {
    const u = new URLSearchParams();
    if (sp.date) u.set("date", sp.date);
    if (sp.symbol) u.set("symbol", sp.symbol);
    if (sp.decision) u.set("decision", sp.decision);
    u.set("page", String(p));
    return "/history?" + u.toString();
  };

  return (
    <>
      <PageHeader title="Lịch sử" desc="Tra cứu tín hiệu theo ngày / mã / decision." />
      <HistoryFilters />
      {rows.length ? (
        <>
          <SignalsTable rows={rows} showDate />
          <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-muted)]">
            <span>
              {total.toLocaleString("vi-VN")} tín hiệu · trang {page}/{totalPages}
            </span>
            <div className="flex gap-2">
              {page > 1 ? (
                <Link href={qs(page - 1)} className="rounded border border-[var(--color-border)] px-3 py-1">
                  ← Trước
                </Link>
              ) : null}
              {page < totalPages ? (
                <Link href={qs(page + 1)} className="rounded border border-[var(--color-border)] px-3 py-1">
                  Sau →
                </Link>
              ) : null}
            </div>
          </div>
        </>
      ) : (
        <EmptyState
          title="Không có tín hiệu khớp"
          hint="Điều chỉnh bộ lọc, hoặc chờ sync đổ data (bảng v4_signals hiện có thể đang rỗng)."
        />
      )}
    </>
  );
}
