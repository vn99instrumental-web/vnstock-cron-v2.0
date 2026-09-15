import { PageHeader, EmptyState } from "@/components/ui";
import { BuyBoard, type BuySignal } from "@/components/buy-board";
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
  const stale = newestRun && newestRun.run_id !== latestBuy.run_id;

  return (
    <>
      <PageHeader
        title="Mua"
        desc={
          `${signals.length} mã BUY / STRONG BUY · run ${latestBuy.run_id}` +
          (stale ? ` (run có BUY gần nhất; run mới nhất ${newestRun!.run_id} chưa có/đủ)` : "") +
          " — chọn 1 mã để xem diễn biến giá + entry/TP"
        }
      />
      <BuyBoard signals={signals} />
    </>
  );
}
