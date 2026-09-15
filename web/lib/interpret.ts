// Diễn giải kỹ thuật "dễ hiểu" từ điểm số factor trong breakdown (ADR-003: con số chính
// thức từ Python; đây chỉ là diễn giải theo DẤU điểm số để người không chuyên đọc được).
// Quy ước: điểm/norm > 0 → nghiêng MUA; < 0 → nghiêng BÁN; 0 → trung tính.
// LƯU Ý: ledger chỉ lưu ĐIỂM factor, KHÔNG lưu giá trị chỉ báo thô (vd Williams %R = -80),
// nên diễn giải theo điểm + tên chỉ báo, không bịa số thô.

export type Dir = "buy" | "sell" | "neutral";

export function dirOf(v: number): Dir {
  if (v > 0.001) return "buy";
  if (v < -0.001) return "sell";
  return "neutral";
}
export const DIR_LABEL: Record<Dir, string> = { buy: "nghiêng MUA", sell: "nghiêng BÁN", neutral: "trung tính" };
export const DIR_COLOR: Record<Dir, string> = {
  buy: "var(--color-buy)",
  sell: "var(--color-sell)",
  neutral: "var(--color-muted)",
};

// 6 nhóm factor (supergroup) — đọc từ trade_<key>_norm (−1..1).
export const FACTOR_META: { key: string; label: string; normKey: string }[] = [
  { key: "mean_reversion", label: "Hồi phục (mean reversion)", normKey: "trade_mean_reversion_norm" },
  { key: "breakout", label: "Bứt phá (breakout)", normKey: "trade_breakout_norm" },
  { key: "flow", label: "Dòng tiền (flow)", normKey: "trade_flow_norm" },
  { key: "fundamental", label: "Cơ bản (fundamental)", normKey: "trade_fundamental_norm" },
  { key: "growth", label: "Tăng trưởng (growth)", normKey: "trade_growth_norm" },
  { key: "context", label: "Bối cảnh (context)", normKey: "trade_context_norm" },
];

// Tín hiệu chi tiết (s_*): tên VN + diễn giải theo dấu.
export const SIGNAL_META: {
  key: string; name: string; buy: string; sell: string;
}[] = [
  { key: "s_willr_mr", name: "Williams %R", buy: "vùng quá bán, khả năng bật lên", sell: "vùng quá mua, dễ điều chỉnh" },
  { key: "s_bb_mr", name: "Bollinger Bands", buy: "chạm dải dưới, hồi lên", sell: "chạm dải trên, căng" },
  { key: "s_overext_ema", name: "Độ giãn khỏi EMA200", buy: "giá bị kéo căng xuống → dễ hồi", sell: "giá căng lên xa EMA" },
  { key: "s_rs_reversal", name: "Đảo chiều sức mạnh (RS)", buy: "đang đảo chiều tăng", sell: "đang yếu đi" },
  { key: "s_deep_dd", name: "Gần đáy 52 tuần", buy: "sát đáy dài hạn → vùng gom", sell: "—" },
  { key: "s_dist_52w", name: "Khoảng cách đỉnh 52T", buy: "gần đỉnh → xu hướng mạnh", sell: "còn xa đỉnh" },
  { key: "s_vol_ratio_h", name: "Khối lượng đột biến", buy: "volume tăng ủng hộ đà", sell: "volume yếu" },
  { key: "s_ff_net", name: "Khối ngoại (dòng tiền)", buy: "nước ngoài mua ròng", sell: "nước ngoài bán ròng" },
  { key: "s_of_phasefix", name: "Order flow (áp lực lệnh)", buy: "lệnh mua chủ động", sell: "lệnh bán chủ động" },
  { key: "s_prop_5d", name: "Tự doanh 5 phiên", buy: "tự doanh mua", sell: "tự doanh bán" },
  { key: "s_insider", name: "Giao dịch nội bộ", buy: "nội bộ mua", sell: "nội bộ bán" },
  { key: "s_fund_core", name: "Cơ bản (định giá/lợi nhuận)", buy: "nền tảng tốt", sell: "nền tảng yếu" },
  { key: "s_growth_core", name: "Tăng trưởng", buy: "tăng trưởng tốt", sell: "tăng trưởng kém" },
  { key: "s_mkt_context", name: "Bối cảnh thị trường", buy: "thị trường thuận", sell: "thị trường bất lợi" },
  { key: "s_trend_st", name: "Xu hướng ngắn hạn", buy: "xu hướng tăng", sell: "xu hướng giảm" },
  { key: "s_depth_wall", name: "Tường thanh khoản", buy: "lực đỡ mua mạnh", sell: "áp lực bán dày" },
  { key: "s_cf_core", name: "Dòng tiền doanh nghiệp", buy: "dòng tiền khỏe", sell: "dòng tiền yếu" },
];

export const CONFIDENCE_LABEL: Record<string, { text: string; color: string }> = {
  HIGH: { text: "Cao", color: "var(--color-buy)" },
  MEDIUM: { text: "Trung bình", color: "#ca8a04" },
  LOW: { text: "Thấp", color: "var(--color-muted)" },
};

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

export interface FactorView { label: string; norm: number; dir: Dir }
export interface SignalView { name: string; score: number; dir: Dir; text: string }

/** Diễn giải 6 nhóm từ breakdown. */
export function factorViews(b: Record<string, unknown>): FactorView[] {
  return FACTOR_META.map((f) => {
    const norm = num(b[f.normKey]) ?? 0;
    return { label: f.label, norm, dir: dirOf(norm) };
  });
}

/** Diễn giải tín hiệu chi tiết có điểm ≠ 0, sắp theo |điểm| giảm dần. */
export function signalViews(b: Record<string, unknown>): SignalView[] {
  const out: SignalView[] = [];
  for (const s of SIGNAL_META) {
    const score = num(b[s.key]);
    if (score == null || score === 0) continue;
    const dir = dirOf(score);
    out.push({ name: s.name, score, dir, text: dir === "buy" ? s.buy : s.sell });
  }
  return out.sort((a, b2) => Math.abs(b2.score) - Math.abs(a.score));
}
