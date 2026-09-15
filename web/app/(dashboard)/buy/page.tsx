import { PageHeader, EmptyState } from "@/components/ui";
import { BuyBoard, type BuySignal } from "@/components/buy-board";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function BuyPage() {
  const supabase = await createClient();

  const { data: run } = await supabase
    .from("v4_runs")
    .select("run_id, started_at")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (!run) {
    return (
      <>
        <PageHeader title="Mua" desc="Mã BUY / STRONG BUY của run mới nhất + diễn biến giá." />
        <EmptyState
          title="Chưa có dữ liệu"
          hint="Bảng v4_signals đang rỗng — chờ sync (E1) chạy."
        />
      </>
    );
  }

  const { data } = await supabase
    .from("v4_signals")
    .select("id, symbol, decision, score_trade, signal_date, breakdown")
    .eq("run_id", run.run_id)
    .in("decision", ["BUY", "STRONG BUY"])
    .order("score_trade", { ascending: false });

  const signals = (data ?? []) as BuySignal[];

  return (
    <>
      <PageHeader
        title="Mua"
        desc={`${signals.length} mã BUY / STRONG BUY · run ${run.run_id} — chọn 1 mã để xem diễn biến giá + entry/TP`}
      />
      <BuyBoard signals={signals} />
    </>
  );
}
