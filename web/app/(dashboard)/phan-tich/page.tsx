import { PageHeader, EmptyState } from "@/components/ui";
import { AnalysisBoard, type SignalResult, type FactorCorr, type FactorPair, type FactorCorrSplit } from "@/components/analysis-board";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const RESULT_COLUMNS =
  "pred_id, symbol, signal_date, snap_time, decision, confidence, t0_close, ret_1d, ret_3d, ret_5d, ret_10d, mfe_pct, mae_pct, own_entry, own_tp1, own_tp2, own_stop, std_outcome, std_days, std3_outcome, own_outcome, own_days";
const PAGE_SIZE = 1000;

export default async function PhanTichPage() {
  const supabase = await createClient();

  const [{ data: firstResults, error: resultsError }, { data: corr }, { data: pairs }, { data: split }] = await Promise.all([
    supabase
      .from("v4_signal_analysis_feed")
      .select(RESULT_COLUMNS)
      .order("signal_date", { ascending: false })
      .order("symbol", { ascending: true })
      .range(0, PAGE_SIZE - 1),
    supabase.from("v4_hit_factor_corr").select("*"),
    supabase.from("v4_factor_pair_corr").select("*"),
    supabase.from("v4_hit_factor_corr_split").select("*"),
  ]);

  if (resultsError) throw resultsError;

  const rows = [...((firstResults ?? []) as SignalResult[])];
  for (let from = PAGE_SIZE; rows.length === from; from += PAGE_SIZE) {
    const { data: next, error } = await supabase
      .from("v4_signal_analysis_feed")
      .select(RESULT_COLUMNS)
      .order("signal_date", { ascending: false })
      .order("symbol", { ascending: true })
      .range(from, from + PAGE_SIZE - 1);
    if (error) throw error;
    const page = (next ?? []) as SignalResult[];
    rows.push(...page);
    if (page.length < PAGE_SIZE) break;
  }

  if (!rows.length) {
    return (
      <>
        <PageHeader
          title="Phân tích tín hiệu"
          desc="Kết quả BUY/STRONG BUY theo thời gian: chạm TP hay SL, và biến đầu vào nào liên quan."
        />
        <EmptyState
          title="Chưa có tín hiệu BUY/STRONG BUY để phân tích"
          hint="Chưa có BUY/STRONG BUY trong bảng v4_signals."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Phân tích tín hiệu"
        desc="Tín hiệu BUY/STRONG BUY mới nhất và kết quả đã đủ 10 phiên: chạm TP hay SL, cùng các biến đầu vào liên quan."
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
