import { PageHeader, EmptyState } from "@/components/ui";
import { BuyBoard, type BuySignal, type ExpectancyRow } from "@/components/buy-board";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function BuyPage() {
  const supabase = await createClient();

  // Run MỚI NHẤT CÓ tín hiệu BUY thực sự trong v4_signals (bền vững kể cả khi run
  // mới nhất chưa sync đủ signals, hoặc tình cờ 0 BUY).
  const { data: latestBuy } = await supabase
    .from("v4_signals")
    .select("run_id, signal_date, snap_time")
    .in("decision", ["BUY", "STRONG BUY"])
    .order("signal_date", { ascending: false })
    .order("snap_time", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (!latestBuy) {
    return (
      <>
        <PageHeader title="Mua" desc="Mã BUY / STRONG BUY + diễn biến giá." />
        <EmptyState
          title="Chưa có mã BUY/STRONG BUY nào trong dữ liệu"
          hint="Chờ sync đổ data, hoặc các phiên gần đây không có tín hiệu mua."
        />
      </>
    );
  }

  // So với run mới nhất tổng thể (để báo nếu đang xem run cũ hơn).
  const { data: newestRun } = await supabase
    .from("v4_runs")
    .select("run_id")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const { data } = await supabase
    .from("v4_signals")
    .select("id, symbol, decision, score_trade, signal_date, breakdown")
    .eq("run_id", latestBuy.run_id)
    .in("decision", ["BUY", "STRONG BUY"])
    .order("score_trade", { ascending: false });

  const signals = (data ?? []) as BuySignal[];

  // % thay đổi so với giá TC (giá đóng cửa phiên liền trước) — lấy prevClose từ v4_ohlc.
  if (signals.length) {
    const sigDate = latestBuy.signal_date as string;
    const since = new Date(new Date(sigDate).getTime() - 14 * 864e5).toISOString().slice(0, 10);
    const { data: ohlc } = await supabase
      .from("v4_ohlc")
      .select("symbol, date, close")
      .in("symbol", signals.map((s) => s.symbol))
      .lt("date", sigDate)
      .gte("date", since)
      .order("date", { ascending: false });
    const prev = new Map<string, number>();
    for (const r of (ohlc ?? []) as { symbol: string; close: number }[]) {
      if (!prev.has(r.symbol)) prev.set(r.symbol, Number(r.close));
    }
    for (const s of signals) {
      const price = Number((s.breakdown ?? {}).price);
      const pc = prev.get(s.symbol);
      s.changePct = pc && Number.isFinite(price) && pc !== 0 ? ((price - pc) / pc) * 100 : null;
    }
  }
  const stale = newestRun && newestRun.run_id !== latestBuy.run_id;

  // Thời điểm run (độ tươi data) + kỳ vọng lịch sử của BUY theo confidence.
  const { data: runRow } = await supabase
    .from("v4_runs")
    .select("started_at")
    .eq("run_id", latestBuy.run_id)
    .maybeSingle();
  const { data: expData } = await supabase.from("v4_buy_expectancy").select("*");

  return (
    <>
      <PageHeader
        title="Mua"
        desc={`${signals.length} mã BUY / STRONG BUY — chọn 1 mã để xem diễn biến giá, entry ±3/6% và kỳ vọng lịch sử`}
      />
      <BuyBoard
        signals={signals}
        expectancy={(expData ?? []) as ExpectancyRow[]}
        runId={latestBuy.run_id}
        runStartedAt={(runRow?.started_at as string | undefined) ?? null}
        newestRunId={(newestRun?.run_id as string | undefined) ?? null}
      />
    </>
  );
}
