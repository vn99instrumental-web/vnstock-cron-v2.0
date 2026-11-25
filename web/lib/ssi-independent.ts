import stored from "@/data/ssi-independent-dashboard.json";

export type SsiDecision = "STRONG BUY" | "BUY" | "NEUTRAL" | "SELL" | "STRONG SELL";
export type SsiLatestRow = {
  pred_id: string; symbol: string; signal_date: string; snap_time: string;
  price: number | null; score_trade: number; score_hold: number; decision: SsiDecision;
  confidence: "HIGH" | "MEDIUM" | "LOW"; regime: string; signal_coverage: number;
  signal_count: number; missing_signals: string[]; available_weight: number;
  signals: Record<string, number | null>; factors: Record<string, number | null>;
  source_provenance: { market: "SSI"; fundamental: "FHSC"; feature_layer: string; gen6_scores_consumed: false; gen6_signals_consumed: false };
};
export type SsiHistoryRow = Pick<SsiLatestRow, "pred_id" | "symbol" | "signal_date" | "snap_time" | "price" | "score_trade" | "score_hold" | "decision" | "confidence" | "signal_coverage"> & { ret_3d: number | null; ret_5d: number | null; ret_10d: number | null };
export type SsiIndependentDashboard = {
  schema_version: 1; version: "ssi-v4.18-independent"; generated_at: string; signal_date: string;
  source_provenance: { market: "SSI"; fundamental: "FHSC"; shared_feature_input: string; calculation: string };
  summary: { symbols: number; history_dates: number; history_rows: number; buy: number; sell: number; full_17_signal_rows: number; minimum_signal_coverage: number; scored_symbols: number };
  latest: SsiLatestRow[]; history: SsiHistoryRow[];
  ic: Record<"ret_3d" | "ret_5d" | "ret_10d", { n: number; pearson: number | null }>;
};

function valid(data: unknown): data is SsiIndependentDashboard {
  if (!data || typeof data !== "object") return false;
  const value = data as Partial<SsiIndependentDashboard>;
  if (value.schema_version !== 1 || value.version !== "ssi-v4.18-independent") return false;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value.signal_date ?? "")) return false;
  if (value.source_provenance?.market !== "SSI" || value.source_provenance?.fundamental !== "FHSC") return false;
  if (!Array.isArray(value.latest) || value.latest.length < 80 || !Array.isArray(value.history)) return false;
  const symbols = new Set<string>();
  for (const row of value.latest) {
    if (!/^[A-Z0-9]{2,12}$/.test(row.symbol) || symbols.has(row.symbol)) return false;
    if (!Number.isFinite(row.score_trade) || !Number.isFinite(row.score_hold)) return false;
    if (row.signal_coverage < 0 || row.signal_coverage > 17 || row.signal_count !== 17) return false;
    if (row.source_provenance?.gen6_scores_consumed !== false || row.source_provenance?.gen6_signals_consumed !== false) return false;
    symbols.add(row.symbol);
  }
  return true;
}

export function getSsiIndependentDashboard(): SsiIndependentDashboard | null {
  return valid(stored) ? stored : null;
}
