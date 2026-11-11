import stored from "@/data/ssi-v418-gen6-shadow.json";

export type V418ShadowSignal = {
  id: string;
  factor: string;
  span: number;
  candidate_points: number | null;
  certified_for_v418: false;
  status: "CANDIDATE_UNCERTIFIED" | "MISSING";
  missing_reason: string | null;
  required_original_fields: string[];
};

export type V418ShadowContribution = {
  known_core_contribution_only: number;
  factor_partial_contributions: Record<string, number>;
  missing_factor_names: string[];
  conditional_regime: "SIDEWAYS_NOT_OBSERVED";
  not_a_total_score: true;
  extras_excluded_and_unknown: true;
};

export type V418ShadowRow = {
  symbol: string;
  source_trade_date: string;
  candidate_signal_count: number;
  original_active_signal_count: 17;
  missing_signal_count: number;
  signals: V418ShadowSignal[];
  scenario_sideways: {
    trade: V418ShadowContribution | null;
    hold: V418ShadowContribution | null;
  };
  source_blockers: unknown[];
  score_trade_ssi: null;
  score_hold_ssi: null;
  decision_ssi: null;
  score_comparable: false;
  can_release_trading_decisions: false;
};

export type V418ShadowDataset = {
  schema_version: 1;
  dataset: "SSI_FINHAY_V418_SHADOW_SOURCE_ONLY";
  target_version: "v4.18";
  reference_commit: string;
  source_trade_date: string;
  source_repository: "vn99instrumental-web/ssi-data-pipeline";
  price_basis: string;
  illustration_regime: "SIDEWAYS_NOT_OBSERVED";
  source_ready_for_final_scoring: false;
  market_regime_certified: false;
  scoring_policy: {
    missing_signal_value: null;
    missing_signals_count_as_zero: false;
    normalize_to_original_full_caps: true;
    renormalize_missing_factor_weights: false;
    extras_when_unverified: null;
    official_trade_and_hold_score: null;
    release_only_after_same_input_parity: true;
  };
  summary: {
    cohort_symbols: 97;
    max_active_signals: 17;
    official_trade_scores: 0;
    official_hold_scores: 0;
    official_buy_sell_decisions: 0;
    candidate_signal_distribution: Record<string, number>;
    symbols_with_any_candidate: number;
  };
  signals: {id: string; factor: string; span: number;
    original_fields: string[]; source_readiness: string}[];
  rows: V418ShadowRow[];
  score_comparable: false;
  can_release_trading_decisions: false;
  signal: "NOT_FOR_TRADING";
};

const FACTORS = ["mean_reversion","breakout","flow","fundamental","growth","context"];

export const V418_SHADOW_SOURCE_URL =
  "https://github.com/vn99instrumental-web/ssi-data-pipeline/blob/main/output/audit/ssi_v418_gen6_shadow.json";

/**
 * Fail closed. This dataset NEVER provides a total v4.18 score/BUY/SELL.
 * A missing point remains null, and SIDEWAYS partial factor contributions
 * are shown as an illustrative scenario, NOT the observed market regime.
 */
export function getSsiV418Shadow(): V418ShadowDataset | null {
  const data = stored as unknown as V418ShadowDataset;
  if (data.schema_version !== 1 ||
      data.dataset !== "SSI_FINHAY_V418_SHADOW_SOURCE_ONLY" ||
      data.target_version !== "v4.18" ||
      data.reference_commit !== "849096d1405bbffebee21a91361d9ce2c32f6d60" ||
      data.source_repository !== "vn99instrumental-web/ssi-data-pipeline" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(data.source_trade_date) ||
      data.source_trade_date !== "2026-11-09" ||
      data.market_regime_certified !== false ||
      data.illustration_regime !== "SIDEWAYS_NOT_OBSERVED" ||
      data.source_ready_for_final_scoring !== false ||
      data.score_comparable !== false ||
      data.can_release_trading_decisions !== false ||
      data.signal !== "NOT_FOR_TRADING" ||
      data.scoring_policy?.missing_signal_value !== null ||
      data.scoring_policy?.missing_signals_count_as_zero !== false ||
      data.scoring_policy?.normalize_to_original_full_caps !== true ||
      data.scoring_policy?.renormalize_missing_factor_weights !== false ||
      data.scoring_policy?.extras_when_unverified !== null ||
      data.scoring_policy?.official_trade_and_hold_score !== null ||
      data.summary?.cohort_symbols !== 97 ||
      data.summary?.max_active_signals !== 17 ||
      data.summary?.official_trade_scores !== 0 ||
      data.summary?.official_hold_scores !== 0 ||
      data.summary?.official_buy_sell_decisions !== 0 ||
      !Array.isArray(data.signals) || data.signals.length !== 17 ||
      !Array.isArray(data.rows) || data.rows.length !== 97) return null;

  const required = new Set(data.signals.map(s=>s.id));
  if (required.size !== 17) return null;
  const symbols = new Set<string>();
  for (const row of data.rows) {
    if (!/^[A-Z0-9]{2,12}$/.test(row.symbol) || symbols.has(row.symbol) ||
        row.source_trade_date !== data.source_trade_date ||
        row.original_active_signal_count !== 17 ||
        !Array.isArray(row.signals) || row.signals.length !== 17 ||
        row.score_trade_ssi !== null || row.score_hold_ssi !== null ||
        row.decision_ssi !== null || row.score_comparable !== false ||
        row.can_release_trading_decisions !== false) return null;
    symbols.add(row.symbol);
    const seen = new Set<string>();
    let candidate = 0;
    for (const s of row.signals) {
      if (!required.has(s.id) || seen.has(s.id) || s.certified_for_v418 !== false)
        return null;
      seen.add(s.id);
      if (s.candidate_points !== null) {
        if (!Number.isInteger(s.candidate_points) ||
            Math.abs(s.candidate_points) > s.span ||
            s.status !== "CANDIDATE_UNCERTIFIED") return null;
        candidate++;
      } else if (s.status !== "MISSING") {
        return null;
      }
    }
    if (candidate !== row.candidate_signal_count ||
        row.missing_signal_count !== 17-candidate ||
        !row.scenario_sideways) return null;
    for (const horizon of ["trade","hold"] as const) {
      const block = row.scenario_sideways[horizon];
      if (!block) continue;
      if (block.conditional_regime !== "SIDEWAYS_NOT_OBSERVED" ||
          block.not_a_total_score !== true ||
          block.extras_excluded_and_unknown !== true ||
          !Number.isFinite(block.known_core_contribution_only) ||
          Object.keys(block.factor_partial_contributions).some(f=>!FACTORS.includes(f))) return null;
    }
  }
  return data;
}
