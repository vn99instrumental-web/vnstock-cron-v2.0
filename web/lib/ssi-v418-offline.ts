import stored from "@/data/ssi-v418-offline-source.json";

export type OfflineMetricKey =
  | "liquid_cohort" | "same_day_ohlc_summary" | "matched_turnover"
  | "foreign_value_valid" | "history_252" | "history_400"
  | "technical_anchor_candidates" | "vnindex_finalized_sessions"
  | "vn100_staged_21day_symbols" | "finhay_pe_pb_direct_sample"
  | "finhay_pit_certified" | "signal_contract_count"
  | "signal_values_v418_parity_certified";

export type OfflineTickerRow = {
  symbol: string;
  trade_date: string;
  ssi_close_as_reported_vnd: string | null;
  ssi_volume_shares: string | null;
  ssi_matched_turnover_vnd: string | null;
  ssi_foreign_net_vnd: string | null;
  ohlc_and_summary_same_day: boolean;
  direct_turnover_verified: boolean;
  foreign_arithmetic_verified: boolean;
  available_history_sessions: number | null;
  has_252_sessions: boolean;
  has_400_sessions: boolean;
  independent_ta_arithmetic_anchor: boolean;
  foreign_flow_status: string;
  score_trade_ssi: null;
  score_hold_ssi: null;
  decision_ssi: null;
  decision_comparable: false;
};
export type OfflineSignal = {
  id: string;
  factor: string;
  source_readiness: string;
  parity_certified: false;
};
export type SsiV418OfflineEvidence = {
  schema_version: 1;
  source_repository: string;
  target_version: "v4.18";
  source_trade_date: string;
  reference_commit: string;
  price_processing_policy: string;
  ssi_vendor_price_adjustment_semantics: "UNVERIFIED";
  event_policy: string;
  comparison_scope: string;
  source_price_direct_comparison_to_vnstock: string;
  score_comparable: false;
  can_release_trading_decisions: false;
  signal: "NOT_FOR_TRADING";
  release_gate_status: "BLOCKED_INPUT";
  metrics: Record<OfflineMetricKey, number> & { vn100_historical_membership_certified: false };
  signals: OfflineSignal[];
  rows: OfflineTickerRow[];
  remaining: string[];
};

export const SSI_V418_AUDIT_SOURCE =
  "https://github.com/vn99instrumental-web/ssi-data-pipeline/blob/main/output/audit/ssi_v418_offline_gen6_export.json";

/** The imported exhibit is intentionally static. Never replace unavailable
 * SSI rows with the upstream VNStock bridge or claim same-input parity. */
export function getSsiV418OfflineEvidence(): SsiV418OfflineEvidence | null {
  const data = stored as unknown as SsiV418OfflineEvidence;
  if (data.schema_version !== 1 ||
      data.source_repository !== "vn99instrumental-web/ssi-data-pipeline" ||
      data.target_version !== "v4.18" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(data.source_trade_date) ||
      data.price_processing_policy !== "SSI_V3_AS_REPORTED_NO_HISTORICAL_BACK_ADJUST" ||
      data.ssi_vendor_price_adjustment_semantics !== "UNVERIFIED" ||
      data.score_comparable !== false || data.can_release_trading_decisions !== false ||
      data.signal !== "NOT_FOR_TRADING" || data.release_gate_status !== "BLOCKED_INPUT" ||
      !Array.isArray(data.rows) || !Array.isArray(data.signals) ||
      data.metrics?.liquid_cohort !== data.rows.length ||
      data.metrics?.signal_contract_count !== 17 ||
      data.signals.length !== 17 ||
      data.metrics?.signal_values_v418_parity_certified !== 0 ||
      data.metrics?.vn100_historical_membership_certified !== false) return null;

  const symbols = new Set<string>();
  for (const row of data.rows) {
    if (!/^[A-Z0-9]{1,10}$/.test(row.symbol) ||
        symbols.has(row.symbol) || row.trade_date !== data.source_trade_date ||
        row.score_trade_ssi !== null || row.score_hold_ssi !== null ||
        row.decision_ssi !== null || row.decision_comparable !== false) return null;
    symbols.add(row.symbol);
  }
  if (data.signals.some((s) => s.parity_certified !== false)) return null;
  return data;
}
