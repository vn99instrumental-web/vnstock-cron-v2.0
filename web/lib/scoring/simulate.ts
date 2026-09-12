// ⚠️ SIMULATION — ước lượng what-if, KHÔNG PHẢI điểm chính thức.
// Nguồn chân lý điểm/quyết định luôn là Python pipeline (golden rule #3, ADR-003).
// Hàm này chỉ ước lượng ảnh hưởng của config (weights × gate) lên score & decision
// để preview khi chỉnh — KHÔNG dùng làm căn cứ promote. Bỏ qua w_reg/extras nội bộ
// của scorer thật; nên kết quả là ĐỊNH HƯỚNG, không khớp tuyệt đối con số production.

export type Factor =
  | "mean_reversion"
  | "breakout"
  | "flow"
  | "fundamental"
  | "growth"
  | "context";

export const FACTORS: Factor[] = [
  "mean_reversion",
  "breakout",
  "flow",
  "fundamental",
  "growth",
  "context",
];

export type WeightSet = Record<Factor, number>;

export interface ScoringConfig {
  version_label: string;
  status?: string;
  factor_weights: { trade: WeightSet; hold: WeightSet };
  gate_matrix: { regimes: string[] } & Record<Factor, number[]>;
  thresholds: { min: number | null; decision: string }[];
  extras?: { confluence_bonus?: number; confluence_min_norm?: number };
}

export type FactorNorms = Partial<Record<Factor, number>>;

export interface SimResult {
  isSimulation: true;
  estScore: number;
  decision: string;
  contributions: { factor: Factor; weight: number; gate: number; norm: number; contribution: number }[];
  note: string;
}

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}

/** Ước lượng decision từ thresholds (giảm dần theo min; min=null là catch-all cuối). */
export function decisionFromScore(
  score: number,
  thresholds: ScoringConfig["thresholds"],
): string {
  const sorted = [...thresholds].sort((a, b) => (b.min ?? -Infinity) - (a.min ?? -Infinity));
  for (const t of sorted) {
    if (t.min === null || score >= t.min) return t.decision;
  }
  return sorted[sorted.length - 1]?.decision ?? "NEUTRAL";
}

/**
 * Ước lượng score & decision cho 1 mã với config đưa vào.
 * @param norms  điểm chuẩn hoá mỗi factor (≈ -1..1), lấy từ trade_<factor>_norm.
 * @param regime tên regime (khớp gate_matrix.regimes).
 */
export function simulate(
  config: ScoringConfig,
  norms: FactorNorms,
  regime: string,
  lens: "trade" | "hold" = "trade",
): SimResult {
  const weights = config.factor_weights[lens];
  const regimes = config.gate_matrix.regimes;
  let ri = regimes.indexOf(regime);
  if (ri < 0) ri = regimes.indexOf("UNKNOWN");
  if (ri < 0) ri = 0;

  const contributions = FACTORS.map((f) => {
    const weight = weights[f] ?? 0;
    const gate = config.gate_matrix[f]?.[ri] ?? 1;
    const norm = norms[f] ?? 0;
    return { factor: f, weight, gate, norm, contribution: weight * gate * norm };
  });

  const raw = contributions.reduce((s, c) => s + c.contribution, 0);
  const estScore = clamp(raw * 100, -100, 100);
  const decision = decisionFromScore(estScore, config.thresholds);

  return {
    isSimulation: true,
    estScore: Math.round(estScore * 100) / 100,
    decision,
    contributions,
    note:
      "SIMULATION — ước lượng (Σ weight×gate×norm ×100, clamp ±100). Bỏ qua w_reg/extras/confluence nội bộ scorer thật. KHÔNG phải điểm chính thức.",
  };
}
