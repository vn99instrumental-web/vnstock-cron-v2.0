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

export const SIGNAL_NAME: Record<string, string> = Object.fromEntries(
  SIGNAL_META.map((s) => [s.key, s.name]),
);
/** Tên tiếng Việt của biến s_* (fallback: chính key). */
export function signalName(key: string): string {
  return SIGNAL_NAME[key] ?? key;
}

// Tên tiếng Việt cho MỌI biến số trong breakdown (dùng ở trang Phân tích tương quan).
export const VAR_NAME: Record<string, string> = {
  ...SIGNAL_NAME,
  trade_mean_reversion_norm: "Nhóm Hồi phục (trade)",
  trade_breakout_norm: "Nhóm Bứt phá (trade)",
  trade_flow_norm: "Nhóm Dòng tiền (trade)",
  trade_fundamental_norm: "Nhóm Cơ bản (trade)",
  trade_growth_norm: "Nhóm Tăng trưởng (trade)",
  trade_context_norm: "Nhóm Bối cảnh (trade)",
  hold_mean_reversion_norm: "Nhóm Hồi phục (hold)",
  hold_breakout_norm: "Nhóm Bứt phá (hold)",
  hold_flow_norm: "Nhóm Dòng tiền (hold)",
  hold_fundamental_norm: "Nhóm Cơ bản (hold)",
  hold_growth_norm: "Nhóm Tăng trưởng (hold)",
  hold_context_norm: "Nhóm Bối cảnh (hold)",
  rank_trend_grp: "Xếp hạng xu hướng (ngành)",
  rank_ff_grp: "Xếp hạng khối ngoại (ngành)",
  rank_fund_grp: "Xếp hạng cơ bản (ngành)",
  rank_fund_uni: "Xếp hạng cơ bản (toàn TT)",
  rank_growth_grp: "Xếp hạng tăng trưởng (ngành)",
  rank_cf_grp: "Xếp hạng dòng tiền DN (ngành)",
  ff_intra_net: "Khối ngoại ròng (VND)",
  ff_intra_frac: "Tỷ trọng khối ngoại",
  ff_intra_ratio: "Tỷ lệ khối ngoại/GT",
  ff_intra_pts: "Điểm khối ngoại",
  ff_intra_flag_pts: "Cờ khối ngoại",
  of_bp_pts: "Điểm order flow (bp)",
  adtv_bil: "Thanh khoản TB (tỷ)",
  confluence_bonus: "Thưởng đồng thuận",
  n_supergroups_aligned: "Số nhóm đồng thuận",
  total_score: "Điểm tổng (trade)",
  score_hold: "Điểm nắm giữ (hold)",
};
/** Tên tiếng Việt cho mọi biến breakdown (fallback: chính key). */
export function varName(key: string): string {
  return VAR_NAME[key] ?? key;
}

// Nhóm biến (khớp cột grp của view v4_hit_factor_corr).
export const GROUP_LABEL: Record<string, string> = {
  signal: "Tín hiệu chi tiết (s_*)",
  factor_trade: "6 nhóm yếu tố — lệnh trade",
  factor_hold: "6 nhóm yếu tố — nắm giữ",
  rank: "Xếp hạng tương đối (rank)",
  flow: "Dòng tiền / khối ngoại",
  other: "Khác",
};
export const GROUP_ORDER = ["signal", "factor_trade", "factor_hold", "rank", "flow", "other"];

// Span (điểm tối đa ±) mỗi chỉ báo — theo utils/v2f_registry.py (SIGNALS + V4_EXTRA).
// Chỉ dùng để diễn giải "điểm X / ±span"; KHÔNG phải trọng số/gate (không hardcode weight).
export const SIGNAL_SPAN: Record<string, number> = {
  s_willr_mr: 6, s_bb_mr: 5, s_overext_ema: 3, s_rs_reversal: 4, s_deep_dd: 4,
  s_dist_52w: 4, s_trend_st: 4, s_vol_ratio_h: 3,
  s_ff_net: 6, s_of_phasefix: 4, s_prop_5d: 3, s_insider: 2, s_depth_wall: 3,
  s_fund_core: 8, s_cf_core: 3, s_growth_core: 5, s_mkt_context: 2,
};

// 6 nhóm yếu tố (FACTORS) → chỉ báo thành viên (theo registry pipeline). normKey = điểm
// tổng hợp nhóm đã chuẩn hoá (−1..1) đọc ĐỘNG từ breakdown; membership khá ổn định.
export const FACTOR_GROUPS: {
  key: string; label: string; normKey: string; members: string[]; desc: string;
}[] = [
  { key: "mean_reversion", label: "Hồi phục (mean reversion)", normKey: "trade_mean_reversion_norm",
    members: ["s_willr_mr", "s_bb_mr", "s_overext_ema", "s_rs_reversal", "s_deep_dd"],
    desc: "Giá bị bán quá đà kỳ vọng bật lại — nhóm mạnh nhất cho lệnh ngắn hạn." },
  { key: "breakout", label: "Bứt phá / xu hướng (breakout)", normKey: "trade_breakout_norm",
    members: ["s_dist_52w", "s_trend_st", "s_vol_ratio_h"],
    desc: "Sức mạnh xu hướng, khoảng cách đỉnh 52 tuần, volume xác nhận đà." },
  { key: "flow", label: "Dòng tiền (flow)", normKey: "trade_flow_norm",
    members: ["s_ff_net", "s_of_phasefix", "s_prop_5d", "s_insider", "s_depth_wall"],
    desc: "Khối ngoại, tự doanh, order flow, tường mua/bán — tiền thực đang vào/ra." },
  { key: "fundamental", label: "Cơ bản (fundamental)", normKey: "trade_fundamental_norm",
    members: ["s_fund_core", "s_cf_core"],
    desc: "Định giá, lợi nhuận, dòng tiền hoạt động doanh nghiệp." },
  { key: "growth", label: "Tăng trưởng (growth)", normKey: "trade_growth_norm",
    members: ["s_growth_core"], desc: "Tốc độ tăng trưởng doanh thu/lợi nhuận." },
  { key: "context", label: "Bối cảnh thị trường (context)", normKey: "trade_context_norm",
    members: ["s_mkt_context"], desc: "Trạng thái thị trường chung." },
];

export interface GroupMemberView { key: string; name: string; score: number; span: number; dir: Dir; text: string }
export interface FactorGroupView { key: string; label: string; desc: string; norm: number; dir: Dir; members: GroupMemberView[] }

/** Diễn giải 6 nhóm + chỉ báo thành viên (điểm, hướng, lý do) từ breakdown. */
export function factorGroupViews(b: Record<string, unknown>): FactorGroupView[] {
  return FACTOR_GROUPS.map((g) => {
    const norm = num(b[g.normKey]) ?? 0;
    const members: GroupMemberView[] = [];
    for (const k of g.members) {
      const score = num(b[k]);
      if (score == null) continue; // chỉ báo không có trong breakdown → bỏ
      const meta = SIGNAL_META.find((s) => s.key === k);
      const dir = dirOf(score);
      members.push({
        key: k, name: meta?.name ?? k, score, span: SIGNAL_SPAN[k] ?? 0, dir,
        text: dir === "buy" ? (meta?.buy ?? "") : dir === "sell" ? (meta?.sell ?? "") : "trung tính",
      });
    }
    members.sort((a, z) => Math.abs(z.score) - Math.abs(a.score));
    return { key: g.key, label: g.label, desc: g.desc, norm, dir: dirOf(norm), members };
  });
}

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
