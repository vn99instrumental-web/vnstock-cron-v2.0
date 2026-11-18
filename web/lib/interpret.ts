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
  adx: "ADX (14)",
  supertrend: "Supertrend (10,3)",
  cash_flow_operating: "Operating cash flow",
  cash_flow_quality: "Operating cash flow / net profit",
  cash_flow_score: "Cash-flow score",
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
  adtv_bil: "GTGD phiên (tỷ)",
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

export interface GroupMemberView { key: string; name: string; score: number; span: number; dir: Dir; text: string; raw?: string }

/** Định dạng VND gọn: tỷ / triệu, kèm dấu. */
function vndShort(v: number): string {
  const a = Math.abs(v);
  const s = v >= 0 ? "+" : "−";
  if (a >= 1e9) return `${s}${(a / 1e9).toFixed(2)} tỷ`;
  if (a >= 1e6) return `${s}${(a / 1e6).toFixed(2)} triệu`;
  return `${s}${a.toFixed(2)}`;
}

function textValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function sourceStatusReason(key: string, b: Record<string, unknown>): string | undefined {
  const statusKey = key === "s_prop_5d" ? "proprietary_flow_status"
    : key === "s_insider" ? "insider_deal_status" : undefined;
  if (!statusKey) return undefined;
  const status = textValue(b[statusKey]);
  switch (status) {
    case "empty_response_unverified":
      return "Ngu\u1ed3n tr\u1ea3 v\u1ec1 r\u1ed7ng; ch\u01b0a x\u00e1c nh\u1eadn l\u00e0 0 giao d\u1ecbch";
    case "unclassified_response":
      return "Ngu\u1ed3n c\u00f3 b\u1ea3n ghi nh\u01b0ng ch\u01b0a ph\u00e2n lo\u1ea1i \u0111\u01b0\u1ee3c";
    case "source_error":
      return "L\u1ed7i ngu\u1ed3n; kh\u00f4ng g\u00e1n gi\u00e1 tr\u1ecb 0";
    case "not_available":
      return "Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u ngu\u1ed3n";
    default:
      return status ? `Tr\u1ea1ng th\u00e1i ngu\u1ed3n: ${status}` : undefined;
  }
}

/**
 * Giá trị THÔ cập nhật đến snapshot ra tín hiệu, gắn kèm 1 số chỉ báo con.
 * Ledger chủ yếu lưu ĐIỂM; chỉ vài field thô có sẵn (thanh khoản, khối ngoại,
 * order flow). Trả null nếu không có field thô cho chỉ báo đó.
 */
function rawAnnot(key: string, b: Record<string, unknown>): string | undefined {
  const g = (k: string) => num(b[k]);
  const price = g("price");
  switch (key) {
    // ── Mean reversion ──
    case "s_willr_mr": {
      const wr = g("willr_14");
      return wr != null ? `Williams %R ${wr.toFixed(2)}` : undefined;
    }
    case "s_bb_mr": {
      const bb = g("bb_position");
      return bb != null ? `%B Bollinger ${bb.toFixed(2)}` : undefined;
    }
    case "s_overext_ema": {
      let d = g("price_vs_ema200_pct");
      const ema = g("ema200");
      if (d == null && price != null && ema != null && ema !== 0) d = ((price - ema) / ema) * 100;
      return d != null ? `Giãn EMA200 ${d >= 0 ? "+" : ""}${d.toFixed(2)}%` : undefined;
    }
    case "s_rs_reversal": {
      const sr = g("return_20d"), vr = g("vnindex_return_20d");
      if (sr == null) return undefined;
      if (vr != null) {
        const rs = (1 + sr / 100) / (1 + vr / 100);
        return `RS 20 phiên ${rs.toFixed(2)} (mã ${sr >= 0 ? "+" : ""}${sr.toFixed(2)}% vs VNI ${vr >= 0 ? "+" : ""}${vr.toFixed(2)}%)`;
      }
      return `Lợi nhuận 20 phiên ${sr >= 0 ? "+" : ""}${sr.toFixed(2)}%`;
    }
    case "s_deep_dd": {
      const lo = g("low_52w");
      return price != null && lo != null && lo !== 0 ? `Trên đáy 52T +${(((price - lo) / lo) * 100).toFixed(2)}%` : undefined;
    }
    // ── Breakout ──
    case "s_dist_52w": {
      const hi = g("high_52w");
      return price != null && hi != null && hi !== 0 ? `Cách đỉnh 52T ${(((price - hi) / hi) * 100).toFixed(2)}%` : undefined;
    }
    case "s_vol_ratio_h": {
      const vr = g("vol_ma_ratio"), adtv = g("adtv_bil");
      const parts: string[] = [];
      if (vr != null) parts.push(`KL ${vr.toFixed(2)}× TB`);
      if (adtv != null) parts.push(`TK ${adtv.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} tỷ`);
      return parts.length ? parts.join(" · ") : undefined;
    }
    // ── Flow ──
    case "s_trend_st": {
      const adx = g("adx"), supertrend = g("supertrend");
      const parts: string[] = [];
      if (adx != null) parts.push(`ADX ${adx.toFixed(2)}`);
      if (supertrend != null) parts.push(`Supertrend ${supertrend.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
      return parts.length ? parts.join(" · ") : undefined;
    }
    case "s_fund_core": {
      const roe = g("ratio_roe"), roa = g("ratio_roa");
      const gross = g("ratio_gross_margin"), net = g("ratio_net_margin");
      const current = g("ratio_current"), debtEquity = g("ratio_debt_equity");
      const parts: string[] = [];
      if (roe != null) parts.push(`ROE ${(roe * 100).toFixed(2)}%`);
      if (roa != null) parts.push(`ROA ${(roa * 100).toFixed(2)}%`);
      if (gross != null) parts.push(`Biên gộp ${(gross * 100).toFixed(2)}%`);
      if (net != null) parts.push(`Biên ròng ${(net * 100).toFixed(2)}%`);
      if (current != null) parts.push(`Current ${current.toFixed(2)}x`);
      if (debtEquity != null) parts.push(`D/E ${debtEquity.toFixed(2)}x`);
      return parts.length ? parts.join(" · ") : undefined;
    }
    case "s_growth_core": {
      const revenue = g("growth_revenue_yoy"), profit = g("growth_profit_yoy");
      const parts: string[] = [];
      if (revenue != null) parts.push(`DT YoY ${revenue >= 0 ? "+" : ""}${(revenue * 100).toFixed(2)}%`);
      if (profit != null) parts.push(`LNST YoY ${profit >= 0 ? "+" : ""}${(profit * 100).toFixed(2)}%`);
      return parts.length ? parts.join(" · ") : undefined;
    }
    case "s_mkt_context": {
      const regime = textValue(b.market_regime) ?? textValue(b.regime);
      const close = g("vnindex_close"), ema20 = g("vnindex_ema20"), ema50 = g("vnindex_ema50");
      const ret20 = g("vnindex_return_20d");
      const parts: string[] = [];
      if (regime) parts.push(regime);
      if (close != null) parts.push(`VN-Index ${close.toLocaleString("vi-VN", { maximumFractionDigits: 2 })}`);
      if (ema20 != null) parts.push(`EMA20 ${ema20.toLocaleString("vi-VN", { maximumFractionDigits: 2 })}`);
      if (ema50 != null) parts.push(`EMA50 ${ema50.toLocaleString("vi-VN", { maximumFractionDigits: 2 })}`);
      if (ret20 != null) parts.push(`20P ${ret20 >= 0 ? "+" : ""}${ret20.toFixed(2)}%`);
      return parts.length ? parts.join(" · ") : undefined;
    }
    case "s_cf_core": {
      const cfo = g("cash_flow_operating"), quality = g("cash_flow_quality");
      const parts: string[] = [];
      if (cfo != null) parts.push(`CFO ${vndShort(cfo)}`);
      if (quality != null) parts.push(`CFO/LNST ${quality.toFixed(2)}x`);
      return parts.length ? parts.join(" · ") : undefined;
    }
    case "s_ff_net": {
      const net = g("ff_intra_net"), ratio = g("ff_intra_ratio");
      if (net == null) return undefined;
      return `KN ròng ${vndShort(net)}${ratio != null ? ` (${(ratio * 100).toFixed(2)}% GT)` : ""}`;
    }
    case "s_prop_5d": {
      const net5 = g("proprietary_net_5d"), net20 = g("proprietary_net_20d");
      const parts: string[] = [];
      if (net5 != null) parts.push(`TD 5P ${vndShort(net5)}`);
      if (net20 != null) parts.push(`20P ${vndShort(net20)}`);
      return parts.length ? parts.join(" · ") : sourceStatusReason(key, b);
    }
    case "s_insider": {
      const buy = g("insider_buy_count"), sell = g("insider_sell_count");
      return buy != null || sell != null ? `B${buy ?? 0}/S${sell ?? 0}` : sourceStatusReason(key, b);
    }
    case "s_depth_wall": {
      const bidVolume = g("depth_bid_volume"), askVolume = g("depth_ask_volume");
      const bidPrice = g("depth_bid_price"), askPrice = g("depth_ask_price");
      const ratio = g("depth_bid_ask_ratio");
      if (bidVolume == null && askVolume == null) return undefined;
      const volume = (value: number | null) => value == null ? "—" : value.toLocaleString("vi-VN", { maximumFractionDigits: 0 });
      const priceAt = (value: number | null) => value == null ? "" : ` @${value.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      return `Bid ${volume(bidVolume)} cp${priceAt(bidPrice)} / Ask ${volume(askVolume)} cp${priceAt(askPrice)}${ratio != null ? ` · B/A ${ratio.toFixed(2)}x` : ""}`;
    }
    case "s_of_phasefix": {
      const spike = g("of_vol_spike_pct");
      if (spike != null)
        return `KL theo pha ${spike >= 0 ? "+" : ""}${spike.toFixed(2)}%`;
      const bp = g("of_bp_pts");
      return bp != null && bp !== 0 ? `Áp lực lệnh ${bp > 0 ? "+" : ""}${bp}` : undefined;
    }
    default:
      return undefined;
  }
}
export interface MissingGroupMemberView { key: string; name: string; reason: string }
export interface FactorGroupView {
  key: string; label: string; desc: string; norm: number; dir: Dir;
  rawTotal: number; spanTotal: number; members: GroupMemberView[]; missing: MissingGroupMemberView[];
}

/** Diễn giải 6 nhóm + chỉ báo thành viên (điểm, hướng, lý do) từ breakdown. */
export function factorGroupViews(b: Record<string, unknown>): FactorGroupView[] {
  return FACTOR_GROUPS.map((g) => {
    const norm = num(b[g.normKey]) ?? 0;
    const members: GroupMemberView[] = [];
    const missing: MissingGroupMemberView[] = [];
    let rawTotal = 0, spanTotal = 0;
    for (const k of g.members) {
      const score = num(b[k]);
      if (score == null) {
        const meta = SIGNAL_META.find((s) => s.key === k);
        const reason = sourceStatusReason(k, b);
        if (reason) missing.push({ key: k, name: meta?.name ?? k, reason });
        continue;
      }
      const meta = SIGNAL_META.find((s) => s.key === k);
      const dir = dirOf(score);
      const span = SIGNAL_SPAN[k] ?? 0;
      rawTotal += score;
      spanTotal += span;
      members.push({
        key: k, name: meta?.name ?? k, score, span, dir,
        text: dir === "buy" ? (meta?.buy ?? "") : dir === "sell" ? (meta?.sell ?? "") : "trung tính",
        raw: rawAnnot(k, b),
      });
    }
    members.sort((a, z) => Math.abs(z.score) - Math.abs(a.score));
    return { key: g.key, label: g.label, desc: g.desc, norm, dir: dirOf(norm), rawTotal, spanTotal, members, missing };
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
