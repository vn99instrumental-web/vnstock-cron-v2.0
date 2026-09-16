import { PageHeader, EmptyState } from "@/components/ui";
import { AnalysisBoard, type SignalResult, type FactorCorr, type FactorPair, type FactorCorrSplit } from "@/components/analysis-board";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function PhanTichPage() {
  const supabase = await createClient();

  const [{ data: results }, { data: corr }, { data: pairs }, { data: split }] = await Promise.all([
    supabase
      .from("v4_signal_results")
      .select(
        "pred_id, symbol, signal_date, snap_time, decision, confidence, t0_close, ret_1d, ret_5d, ret_10d, mfe_pct, mae_pct, own_entry, own_tp1, own_tp2, own_stop, std_outcome, std_days, std3_outcome, own_outcome, own_days",
      )
      .order("signal_date", { ascending: false }),
    supabase.from("v4_hit_factor_corr").select("*"),
    supabase.from("v4_factor_pair_corr").select("*"),
    supabase.from("v4_hit_factor_corr_split").select("*"),
  ]);

  const rows = (results ?? []) as SignalResult[];

  if (!rows.length) {
    return (
      <>
        <PageHeader
          title="Phân tích tín hiệu"
          desc="Kết quả BUY/STRONG BUY theo thời gian: chạm TP hay SL, và biến đầu vào nào liên quan."
        />
        <EmptyState
          title="Chưa có tín hiệu nào đủ chín để phân tích"
          hint="Kết quả chỉ tính được sau khi outcome forward chín (~3 tuần sau tín hiệu)."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Phân tích tín hiệu"
        desc="Kết quả BUY/STRONG BUY theo thời gian: chạm TP hay SL (đi theo nến thật), và biến đầu vào nào liên quan."
      />
      <AnalysisBoard
        results={rows}
        corr={(corr ?? []) as FactorCorr[]}
        pairs={(pairs ?? []) as FactorPair[]}
        split={(split ?? []) as FactorCorrSplit[]}
      />
    </>
  );
}
