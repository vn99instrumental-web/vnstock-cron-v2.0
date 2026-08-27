"""
utils/v2f_registry.py — SIGNAL REGISTRY cho scoring v3 (track V2F, shadow)
============================================================================
TRÁI TIM của v3: toàn bộ tín hiệu khai báo trong MỘT bảng. Engine
(v2f_step_scoring_v3.py) chỉ đọc bảng này — không hard-code tín hiệu nào.

CẤU TRÚC MỖI ENTRY:
  id        : tên duy nhất
  factor    : 1 trong FACTORS (nhóm trực giao, thay 12 group chồng chéo cũ)
  fn        : tên hàm chấm trong engine (engine validate tồn tại lúc load)
  span      : điểm tối đa MỖI CHIỀU — ĐỐI XỨNG là bắt buộc: hàm chấm chỉ
              được trả giá trị trong [-span, +span]; engine validate runtime.
  horizons  : ("trade",) / ("hold",) / ("trade","hold")
  status    : "active" | "off" | "gate:down" | "gate:up"
              gate:* = chờ regime gate Phase 2 — engine hiện SKIP (log rõ).
  source    : "raw" (tính từ v2f_deep_raw) | "inherited" (renorm từ điểm
              v2.3 trong v2f_signals.json — phần chưa redesign)
  ic_ref    : IC 5d/20d lần calibration gần nhất (evidence 04/07/2026)
  note      : lý do quyết định — truy vết về bảng evidence

CAP TỰ TÍNH (chặn vĩnh viễn lỗi "thang điểm ảo" của v2.3):
  cap(horizon, factor) = Σ span của entry active có horizon & factor đó.
  KHÔNG tồn tại con số cap viết tay ở bất kỳ đâu.

SỐ PHẬN 22 TÍN HIỆU CŨ (evidence signal_ic_20260704):
  GIỮ+thăng cấp : willr(±3→±6), bb, dist_52w
  ĐẢO DẤU       : overext_ema (=price_vs_ema200 đảo), rs_reversal (=RS đảo)
  BỎ (bản sao)  : ema_cross, macd, roc10, obv_confirm, efi, ad_slope
  BỎ (IC≈0)     : rsi, mfi
  GATE:down     : cmf, stoch (chỉ có edge khi regime down: +0.076/+0.036)
  CHUYỂN HOLD   : vol_ratio (WEAK 5d nhưng KEEP 20d, t=2.1)
  OFF+watchlist : adx_confirm, aroon, supertrend, linreg, nr7, donchian

CHANGELOG:
  registry_version 1 (2026-07-04) — initial theo DESIGN_V2F_SCORING_V3.md.
  ⚠️ MỌI thay đổi bảng SIGNALS → bump REGISTRY_VERSION (ghi vào ledger v3).
"""

REGISTRY_VERSION = 2  # v2: + tín hiệu deep_dd (mean_reversion, span 4). cap MR trade 20->24.

FACTORS = ("mean_reversion", "breakout", "flow",
           "fundamental", "growth", "context")

# Weight theo KHUNG — 2 bảng điểm từ 1 lần tính (xem DESIGN mục 4b)
FACTOR_WEIGHTS = {
    "trade": {   # 1-5 ngày — nghiêng mean-reversion (evidence: MR thắng áp đảo)
        "mean_reversion": 0.30,
        "breakout":       0.08,
        "flow":           0.25,
        "fundamental":    0.20,
        "growth":         0.10,
        "context":        0.07,
    },
    "hold": {    # ~1 tháng — dist_52w anchor (t=5.8), fundamentals nặng hơn
        "mean_reversion": 0.15,
        "breakout":       0.28,
        "flow":           0.12,
        "fundamental":    0.25,
        "growth":         0.15,
        "context":        0.05,
    },
}

# Ngưỡng decision (chỉ khung TRADE — hold chỉ xuất điểm + rank, không phát lệnh)
THRESHOLDS = [(50, "STRONG BUY"), (25, "BUY"), (-10, "NEUTRAL"),
              (-25, "SELL"), (None, "STRONG SELL")]

CONFLUENCE_BONUS   = 5     # tối đa ±5, NẰM TRONG clamp ±100 (khác v2.3: +10 ngoài hệ)
CONFLUENCE_MIN_NORM = 0.30

# (id, factor, fn, span, horizons, status, source, ic_ref, note)
SIGNALS = [
    # ── MEAN REVERSION ──────────────────────────────────────────────────
    ("willr_mr",     "mean_reversion", "sc_willr",      6, ("trade", "hold"),
     "active", "raw",       "+0.033/+0.020",
     "Anchor MR — mạnh nhất khung trade (t=4.4), STABLE_POS 4/5 quý"),
    ("bb_mr",        "mean_reversion", "sc_bb",         5, ("trade", "hold"),
     "active", "raw",       "+0.031/+0.021",
     "KEEP trade; 20d STABLE_POS theo quý (3 quý gần +0.07..+0.10)"),
    ("overext_ema",  "mean_reversion", "sc_overext",    5, ("trade", "hold"),
     "active", "raw",       "+0.034/+0.049",
     "= price_vs_ema200 ĐẢO DẤU (fade căng); gốc STABLE_NEG 5/5 quý"),
    ("rs_reversal",  "mean_reversion", "sc_rs_rev",     4, ("trade", "hold"),
     "active", "raw",       "+0.038/+0.025",
     "= RS 20d ĐẢO DẤU; gốc STABLE_NEG 5/5 quý"),
    ("deep_dd",      "mean_reversion", "sc_deepdd",     4, ("trade", "hold"),
     "active", "raw",       "exc5d+1.38%/exc10d+1.46% (7 phien, INDICATIVE)",
     "Gần đáy 52T → điểm + (một chiều, span 4). low_52w có sẵn. Bằng chứng "
     "dưới guard 30 — cần forward mới; nửa sát-đáy chưa kiểm riêng"),
    ("cmf_mr",       "mean_reversion", "sc_cmf",        3, ("trade",),
     "gate:down", "raw",    "down:+0.076",
     "Chỉ có edge khi regime down — chờ gate Phase 2"),
    ("stoch_mr",     "mean_reversion", "sc_stoch",      3, ("trade",),
     "gate:down", "raw",    "down:+0.036",
     "Chỉ có edge khi regime down — chờ gate Phase 2"),

    # ── BREAKOUT ────────────────────────────────────────────────────────
    ("dist_52w",     "breakout",       "sc_52w",        4, ("trade", "hold"),
     "active", "raw",       "+0.034/+0.063",
     "Anchor HOLD (t20=5.8); v4.14 MỘT CHIỀU: bỏ phạt đáy, chỉ thưởng gần đỉnh "
     "(vùng đáy nhường deep_dd) — hết triệt tiêu ở đáy"),
    ("vol_ratio_h",  "breakout",       "sc_vol_ratio",  3, ("hold",),
     "active", "raw",       "5d:~0 / 20d:+0.021",
     "CHUYỂN KHUNG: volume đột biến đi trước đà 1 tháng (t20=2.1)"),

    # ── FLOW (kế thừa v2.3 phần tốt + fix phase order flow) ─────────────
    ("ff_net",       "flow",           "sc_ff",         6, ("trade", "hold"),
     "active", "inherited", None,
     "FF v2.3 dead-band 0.10 (fix tốt, giữ nguyên) — renorm max ±18 → ±6"),
    ("of_phasefix",  "flow",           "sc_of",         4, ("trade",),
     "active", "raw",       None,
     "Order flow SAU fix phase intraday (expected-fraction curve, DESIGN mục 5)"),
    ("prop_5d",      "flow",           "sc_prop",       3, ("trade", "hold"),
     "active", "inherited", "PartA-INDICATIVE",
     "Renorm ±10→±3; dead-band riêng defer — Part A tự tích lũy evidence"),
    ("insider",      "flow",           "sc_insider",    2, ("trade", "hold"),
     "active", "inherited", "PartA-INDICATIVE", "Renorm ±5→±2"),

    # ── FUNDAMENTAL / GROWTH / CONTEXT (kế thừa, renorm đúng max thật) ──
    ("fund_core",    "fundamental",    "sc_fund",       8, ("trade", "hold"),
     "active", "inherited", None,
     "fundamental_score v2.3 TRỪ ext_fv (FairVal naive → off); max 23 → ±8"),
    ("growth_core",  "growth",         "sc_growth",     5, ("trade", "hold"),
     "active", "inherited", None, "growth_score v2.3 (max ±15) → ±5"),
    ("mkt_context",  "context",        "sc_context",    2, ("trade", "hold"),
     "active", "inherited", None,
     "context v2.3 trừ breadth stub (max thật ±5) → ±2; breadth về Phase 2"),

    # ── OFF + WATCHLIST (vẫn khai báo để calibration loop theo dõi) ─────
    ("adx_watch",    "mean_reversion", "sc_none", 0, ("trade",),
     "off", "raw", "up:+0.019/down:-0.075", "Watchlist gate:up — chưa đủ mạnh"),
    ("aroon_watch",  "breakout",       "sc_none", 0, ("trade",),
     "off", "raw", "up:+0.030/down:-0.032", "Watchlist gate:up"),
]


# ══════════════════════════════════════════════════════════════════════
# VALIDATION + AUTO-CAPS — engine gọi lúc load, sai là raise ngay
# ══════════════════════════════════════════════════════════════════════

def validate_registry() -> None:
    ids = [s[0] for s in SIGNALS]
    if len(ids) != len(set(ids)):
        raise ValueError("Registry: id trùng lặp")
    for sid, factor, fn, span, horizons, status, source, _, _ in SIGNALS:
        if factor not in FACTORS:
            raise ValueError(f"{sid}: factor '{factor}' không hợp lệ")
        if not isinstance(span, int) or span < 0:
            raise ValueError(f"{sid}: span phải là int >= 0")
        if status == "active" and span == 0:
            raise ValueError(f"{sid}: active nhưng span=0")
        for h in horizons:
            if h not in ("trade", "hold"):
                raise ValueError(f"{sid}: horizon '{h}' không hợp lệ")
        if status not in ("active", "off") and not status.startswith("gate:"):
            raise ValueError(f"{sid}: status '{status}' không hợp lệ")
        if source not in ("raw", "inherited"):
            raise ValueError(f"{sid}: source '{source}' không hợp lệ")
    for hz, w in FACTOR_WEIGHTS.items():
        total = sum(w.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"FACTOR_WEIGHTS[{hz}] tổng={total} != 1.0")
        if set(w) != set(FACTORS):
            raise ValueError(f"FACTOR_WEIGHTS[{hz}] thiếu/thừa factor")


def active_signals(horizon: str) -> list:
    """Entry active cho 1 khung (gate:* KHÔNG tính — chờ Phase 2)."""
    return [s for s in SIGNALS
            if s[5] == "active" and horizon in s[4]]


def factor_caps(horizon: str) -> dict:
    """Cap tự tính = Σ span active theo (horizon, factor). Factor không có
    tín hiệu active → cap 0 → engine coi norm = 0 (không chia 0)."""
    caps = {f: 0 for f in FACTORS}
    for sid, factor, fn, span, horizons, status, source, _, _ in \
            active_signals(horizon):
        caps[factor] += span
    return caps


if __name__ == "__main__":
    validate_registry()
    for hz in ("trade", "hold"):
        print(f"[{hz}] caps auto:", factor_caps(hz),
              "| signals:", [s[0] for s in active_signals(hz)])
      
# ══════════════════════════════════════════════════════════════════════
# GATE MATRIX v2 (V4 / RCEG) — điều kiện theo REGIME.  V3 KHÔNG đọc phần này.
# THAY khối GATE v1 đã dán trước đó bằng khối này (GATE_VERSION 1 → 2).
# gate ∈ [0,1] = hệ số nhân lên weight của factor theo regime hiện tại.
#
# CĂN CỨ (Phase A, đo trên tier liquid, log 2026-07-29):
#   mean_reversion: TẮT MỌI regime (v4, 2026-08-13). UP/SIDEWAYS đã = 0 (IC≈0/âm,
#                   B1); DOWN/DEEP 1.0→0.0 vì forward IC −0.167 (đỡ giá SAI trong
#                   down). A2 backtest gap +1.30% bị forward phản bác.
#   breakout      : SIDEWAYS 0.7 (3 tín hiệu dương cả 2 nửa, mẫu mỏng → thận
#                   trọng); UPTREND 0.5 (chỉ dist_52w & ✗FLIP → nửa liều).
#                   DOWN/DEEP = 1.0 (v3, 2026-08-13): A1 backtest cũ ghi
#                   anti-predictive (t≤-2) → gate 0; forward THẬT ĐẢO NGƯỢC.
#   flow/fund/growth/context: inherited-pending (A3 trống — chờ forward/backfill FF).
#   UNKNOWN       : bảo thủ (MR tắt; breakout nửa liều) — dùng khi API VNINDEX fail.
#
# CHANGELOG GATE:
#   v2 (2026-07-29) — Phase A: MR gated down-only; breakout tắt down (A1 backtest).
#   v3 (2026-08-13) — breakout DOWN/DEEP 0.0 → 1.0. Bằng chứng FORWARD (join
#       v2f_predictions→v2f_outcomes, ~18 phiên giảm 24/06–24/07, daily-last):
#         • IC(breakout_norm → r5d) = +0.31 trong phiên giảm (DỰ BÁO ĐÚNG, KHÔNG
#           anti); bỏ breakout làm IC điểm tổng xấu đi (−0.01 → −0.085).
#         • V2.3 (không gate) giữ trend BẬT: trend_score IC +0.18, total_score
#           IC +0.14, lệnh SELL đúng 74% trong down → lợi thế downtrend ĐẾN TỪ
#           factor trend; V4 gate 0 = tự vứt đúng cái đó.
#       A1 backtest (in-sample, đã cạn) bị forward phản bác → quy tắc 23/07:
#       forward thắng. CHỈ đổi breakout; mean_reversion (forward IC −0.167, nên
#       tắt down) để chu kỳ sau — kỷ luật 1 thay đổi/chu kỳ. Mẫu ~18 phiên giảm
#       của MỘT nhịp → INDICATIVE (dưới guard 30 phiên), theo dõi forward tiếp.
#   v4 (2026-08-13) — mean_reversion DOWN/DEEP 1.0 → 0.0 (giờ MR TẮT MỌI regime).
#       Forward IC(mr_norm → r5d) = −0.167 trong phiên giảm (đỡ giá sai). Cùng
#       CHU KỲ với v3 theo yêu cầu người dùng — CHẤP NHẬN 2 thay đổi liền tay,
#       cần đủ forward để tách đóng góp từng cái. Hệ quả (Cách B): DOWN w_regime
#       1.0 → 0.73, ngưỡng decision co theo → SELL dễ chạm hơn (đúng ý trong down).
#   v6 (2026-08-20) — fundamental & growth: DOWN 1.0→0.8, DEEP 1.0→0.6 (UP/SIDE
#       giữ 1.0). CĂN CỨ (đo trên file live 2026-08-20, DEEP_DOWN toàn rổ):
#         • Refresh finance Q2 (tháng earnings, TTL=3) nạp lại fundamental sau 2
#           phiên trống (08-17/18 fund_norm=0). fund_norm bật 0 → +0.366 (08-19)
#           → +0.486 (08-20), 111/130 mã dương. Giá gần đứng yên → KHÔNG do PE co.
#         • fundamental đóng +16.1đ/mã cho nhóm BUY (lớn nhất), growth +3.7đ; MR
#           +9.2đ. fund+MR một mình = +25.3 ≥ ngưỡng 25 → tự tạo BUY dù breakout
#           âm (−0.7đ, đúng chiều giảm) và breadth chỉ 21.5%.
#         • DEEP_DOWN: mọi gate=1.0 → w_reg=1.0 → ngưỡng KHÔNG hạ; fundamental
#           (gate 1.0 mọi regime) bơm BUY bất kể regime. Số BUY nhảy 0–8 (15 phiên
#           trước) → 8 (08-19) → 21 (08-20). Bất thường THẬT.
#         • Neo giá trị theo NGUYÊN TẮC (không fit đếm): g≤0.68 đảm bảo fund+growth
#           đạt max (norm=+1) cũng KHÔNG tự vượt ngưỡng BUY — "originate-guard",
#           chỉ nâng hạng chứ không tạo lệnh. Chọn 0.6 (biên nhẹ: max slow 19.6 <
#           ngưỡng 21.7). Sim: BUY 21→7 (mức downtrend bình thường), SELL 7→8.
#       ⚠️ CÙNG CHU KỲ chỉ 1 thay đổi (gate fund+growth, coi là 1 cụm slow-factor).
#       Đổi PRODUCTION ngay (Đường 2) + shadow ngược gate=1.0 (score_trade_gate1 /
#       decision_gate1) để forward so gated vs cũ. Cross-section 1 phiên là KHỞI
#       ĐIỂM, forward IC ≥30 phiên mới là phán quyết (giữ/chỉnh mức gate).
# ⚠️ Đổi bất kỳ số nào → bump GATE_VERSION (reset bucket forward-validation v4).
# ══════════════════════════════════════════════════════════════════════
GATE_VERSION = 7
REGIMES = ("UPTREND", "SIDEWAYS", "RECOVERY", "DOWNTREND", "DEEP_DOWN", "UNKNOWN")
_REGIME_IDX = {r: i for i, r in enumerate(REGIMES)}

# thứ tự cột = REGIMES ở trên
GATE = {
    #                 UP    SIDE  RECOV DOWN  DEEP  UNKNOWN   # nguồn
    "mean_reversion": (1.0,  1.0,  1.0,  1.0,  1.0,  1.0),    # v5: BẬT LẠI mọi regime (quyết định vận hành 2026-08-16 — kiểm production thủ công; LƯU Ý file từng ghi forward IC −0.167, cần re-validate)
    "breakout":       (0.5,  0.7,  0.5,  1.0,  1.0,  0.5),    # v3: down/deep bật lại (forward IC +0.31). UPTREND giữ 0.5: thử nâng 0.7 nhưng ngưỡng ×w_reg tự bù → không nới được BUY (sim 2026-08-16), revert.
    "flow":           (1.0,  1.0,  1.0,  1.0,  1.0,  1.0),    # inherited-pending
    "fundamental":    (1.0,  1.0,  0.8,  0.8,  0.6,  1.0),    # v6: gate DOWN/DEEP (2026-08-20) — chặn value-trap. Refresh Q2 làm fund_norm 0→+0.49 toàn rổ → 21 BUY trong DEEP_DOWN. 0.6 = "originate-guard": fund+growth max KHÔNG tự vượt ngưỡng BUY (g≤0.68). Sim cross-section: BUY 21→7, SELL ~không đổi.
    "growth":         (1.0,  1.0,  0.8,  0.8,  0.6,  1.0),    # v6: gate cùng nhịp fundamental — growth cũng là tín hiệu chậm, không time 1–5d; giữ tính chất originate-guard của cả cụm slow-factor.
    "context":        (1.0,  1.0,  1.0,  1.0,  1.0,  1.0),    # đã regime-aware nội bộ
}


def gate_for(factor: str, regime: str) -> float:
    """Hệ số gate của 1 factor theo regime. Factor/regime lạ → 1.0 (an toàn:
    không tự ý tắt cái chưa khai báo)."""
    row = GATE.get(factor)
    if not row:
        return 1.0
    return row[_REGIME_IDX.get(regime, _REGIME_IDX["UNKNOWN"])]
