import type { ScoringConfig } from "./simulate";

// Baseline mirror config/scoring/active.json (registry v4.17). Dùng khi v4_scoring_configs rỗng.
// KHÔNG phải nguồn chân lý scoring — chỉ điểm khởi đầu cho editor.
export const DEFAULT_CONFIG: ScoringConfig = {
  version_label: "v4.17-baseline",
  status: "production",
  factor_weights: {
    trade: {
      mean_reversion: 0.3,
      breakout: 0.08,
      flow: 0.25,
      fundamental: 0.2,
      growth: 0.1,
      context: 0.07,
    },
    hold: {
      mean_reversion: 0.15,
      breakout: 0.28,
      flow: 0.12,
      fundamental: 0.25,
      growth: 0.15,
      context: 0.05,
    },
  },
  gate_matrix: {
    regimes: ["UPTREND", "SIDEWAYS", "RECOVERY", "DOWNTREND", "DEEP_DOWN", "UNKNOWN"],
    mean_reversion: [1, 1, 1, 1, 1, 1],
    breakout: [0.5, 0.7, 0.5, 1, 1, 0.5],
    flow: [1, 1, 1, 1, 1, 1],
    fundamental: [1, 1, 0.8, 0.8, 0.6, 1],
    growth: [1, 1, 0.8, 0.8, 0.6, 1],
    context: [1, 1, 1, 1, 1, 1],
  },
  thresholds: [
    { min: 50, decision: "STRONG BUY" },
    { min: 25, decision: "BUY" },
    { min: -10, decision: "NEUTRAL" },
    { min: -25, decision: "SELL" },
    { min: null, decision: "STRONG SELL" },
  ],
  extras: { confluence_bonus: 5, confluence_min_norm: 0.3 },
};
