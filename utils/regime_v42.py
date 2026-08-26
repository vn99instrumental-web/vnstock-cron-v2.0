"""
utils/regime_v42.py — Market Regime v4.2 candidate (SHADOW)
========================================================
MỘT NGUỒN LOGIC DUY NHẤT cho regime v4.2 (candidate). step3_context.py,
step_context_refresh.py và scripts/diag_regime_v42.py đều import từ đây
→ không bao giờ lệch nhau (fix luôn cái smell duplicate logic v2 ở 2 file).

TRẠNG THÁI: SHADOW-ONLY. Không module scoring nào được import gate từ đây
cho tới khi shadow validation pass (sau 06/08/2026). market_regime (đang dùng)
vẫn là nguồn duy nhất cho scoring/gate V4 production.

═══════════════════════════════════════════════════════════════════════
THIẾT KẾ (pre-registered 2026-08-03 — KHÔNG chỉnh ngưỡng sau khi chạy)
═══════════════════════════════════════════════════════════════════════
Vấn đề v2: DEEP_DOWN chỉ đo VỊ TRÍ (dưới 2 EMA), mù momentum.
  → 03/08/2026: VNINDEX +1.16%/1d, +5.21%/5d nhưng vẫn dán DEEP_DOWN.
Fix (v4.2 candidate): 2 chiều VỊ TRÍ × ĐÀ, thêm state RECOVERY (hồi từ vùng yếu).

Phân loại (đánh giá THEO THỨ TỰ, khớp đầu tiên thắng):
  1. DEEP_DOWN : (dưới cả 2 EMA VÀ chg_5d ≤ 0)  HOẶC  chg_20d ≤ −8
                 (crash-rule ưu tiên: −8%/20d mà bật 3 ngày vẫn là bear-
                  market rally dễ fail → risk trumps recovery)
  2. RECOVERY  : dưới EMA50 VÀ chg_5d ≥ +2  (revised 08-03: +3→+2)
  3. DOWNTREND : dưới EMA50 VÀ (chg_20d ≤ −2 HOẶC chg_5d ≤ −3)
  4. UPTREND   : trên cả 2 EMA VÀ chg_20d > 0
  5. SIDEWAYS  : còn lại

Hysteresis (chống nhảy loạn — trả lời Phase A4):
  - BẤT ĐỐI XỨNG: vào DEEP_DOWN qua crash-rule (chg_20d ≤ −8) = chuyển
    NGAY (risk control phải nhanh — chuẩn drawdown management).
  - Mọi chuyển state khác: raw label mới phải xuất hiện ở phiên hiện tại
    VÀ ở entry cuối của PHIÊN TRƯỚC (2 phiên liên tiếp xác nhận).
    Chưa đủ → giữ state cũ, đánh dấu pending.
  - Bootstrap (chưa có log phiên trước) → nhận raw ngay.

═══════════════════════════════════════════════════════════════════════
CĂN CỨ HỌC THUẬT cho gate V4.1 (vì backtest dataset đã cạn sau 37 test,
gate RECOVERY được NỘI SUY CÓ CĂN CỨ từ literature + Phase A hiện có,
sau đó validate FORWARD — không mining thêm)
═══════════════════════════════════════════════════════════════════════
  • Hamilton (1989) — regime-switching: thị trường có state rời rạc và
    TRẠNG THÁI CHUYỂN TIẾP; ép mọi thứ vào up/down/sideways làm mất
    thông tin ở điểm ngoặt (đúng lỗi hôm nay).
  • Lehmann (1990), Jegadeesh (1990) — short-term reversal: premium đảo
    chiều mạnh nhất NGAY SAU cú giảm; khi giá đã bật +3–5% thì phần
    premium còn lại suy giảm → MR trong RECOVERY = 0.5 (nửa liều),
    không phải 1.0 như DEEP_DOWN.
  • Moskowitz–Ooi–Pedersen (2012) — time-series momentum: lợi nhuận trend
    tập trung ở trend ĐÃ THÀNH LẬP, yếu/âm quanh điểm đảo chiều →
    breakout trong RECOVERY chỉ hé 0.3, chưa mở 0.7 như SIDEWAYS.
  • O'Neil — follow-through day: đáy chỉ được xác nhận ở ngày 4–7 của
    rally attempt kèm volume; trước xác nhận, exposure giữ nhỏ →
    RECOVERY là "rally attempt chưa xác nhận", gate thấp là đúng.
  • Khớp Phase A nội bộ: MR-down IC +0.13, gap +1.3% (còn edge trong
    down); breakout-down âm (đã tắt). RECOVERY nằm GIỮA hai môi trường
    đó → gate nội suy giữa là nhất quán với đo đạc của chính hệ thống.
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────
# NGƯỠNG PRE-REGISTERED (khoá 2026-08-03, chỉ đổi qua review có ghi chép)
# ─────────────────────────────────────────────────────────────────────
TH_CRASH_20D     = -8.0   # chg_20d ≤ −8  → DEEP_DOWN ngay (crash rule)
TH_DEEP_C5       =  0.0   # dưới 2 EMA + chg_5d ≤ 0 → DEEP_DOWN
TH_RECOVERY_C5   =  2.0   # dưới EMA50 + chg_5d ≥ +2 → RECOVERY
                          # REVISION 2026-08-03 (1 lần, có ghi chép):
                          # +3 → +2. Căn cứ EPISODE-SPECIFIC (không fit
                          # AC): cú hồi 07/2026 đo được chạy +2.17→+2.66
                          # →+2.95% suốt 3 phiên trước khi vượt +3, nên
                          # +3 bỏ lỡ đúng đoạn hồi. +2 bắt đúng đoạn đó.
                          # Vẫn buộc dưới EMA50 → không fire trong uptrend.
TH_DOWN_C20      = -2.0   # DOWNTREND leg 1
TH_DOWN_C5       = -3.0   # DOWNTREND leg 2
CONFIRM_SESSIONS =  2     # hysteresis: 2 phiên liên tiếp xác nhận

REGIME_V3_STATES = ("UPTREND", "SIDEWAYS", "RECOVERY",
                    "DOWNTREND", "DEEP_DOWN")

# ─────────────────────────────────────────────────────────────────────
# GATE MA TRẬN V4.1 ĐỀ XUẤT — SHADOW ONLY, CHƯA WIRE VÀO SCORING.
# UPTREND/SIDEWAYS/DOWNTREND/DEEP_DOWN giữ NGUYÊN V4 (đã calibrate
# Phase A). Chỉ THÊM hàng RECOVERY (nội suy có căn cứ, xem docstring).
# ─────────────────────────────────────────────────────────────────────
GATE_V41_PROPOSED = {
    "mean_reversion": {"UPTREND": 0.0, "SIDEWAYS": 0.0, "RECOVERY": 0.5,
                       "DOWNTREND": 1.0, "DEEP_DOWN": 1.0},
    "breakout":       {"UPTREND": 0.5, "SIDEWAYS": 0.7, "RECOVERY": 0.3,
                       "DOWNTREND": 0.0, "DEEP_DOWN": 0.0},
    "flow_fund":      {"UPTREND": 1.0, "SIDEWAYS": 1.0, "RECOVERY": 1.0,
                       "DOWNTREND": 1.0, "DEEP_DOWN": 1.0},
}

# Context matrix V4.1 đề xuất — hàng RECOVERY nằm giữa DOWNTREND và
# SIDEWAYS (hồi chưa xác nhận: bớt phạt so với down, chưa thưởng).
CONTEXT_MATRIX_V41_PROPOSED = {
    "CHEAP":     {"UPTREND":  5, "SIDEWAYS":  3, "RECOVERY":  1,
                  "DOWNTREND":  0, "DEEP_DOWN": -2},
    "FAIR":      {"UPTREND":  2, "SIDEWAYS":  0, "RECOVERY": -1,
                  "DOWNTREND": -2, "DEEP_DOWN": -4},
    "EXPENSIVE": {"UPTREND": -2, "SIDEWAYS": -3, "RECOVERY": -3,
                  "DOWNTREND": -4, "DEEP_DOWN": -5},
}

# Cảnh báo hiển thị kèm BUY/STRONG BUY khi regime v4.2 = RECOVERY
# (KHÔNG đổi ngưỡng 80/40/−15/−40 — walk-forward đã chứng minh tuning
#  ngưỡng/trọng số không thắng coin flip. Regime tác động qua gate,
#  còn đây chỉ là flag hiển thị.)
RECOVERY_BUY_WARNING = "song hoi chua xac nhan dao chieu"


# ─────────────────────────────────────────────────────────────────────
# OP1 — REGIME LIVE MỖI RUN theo DẤU của m2 (wired vào scoring_v4 index_raw)
# ─────────────────────────────────────────────────────────────────────
# m2 = đà HÔM QUA + đà HÔM NAY (có dấu). Phân trạng thái theo DẤU của m2 +
# chiều của hôm nay — KHÔNG dùng ngưỡng độ lớn, KHÔNG dùng EMA/vị trí.
#   |chg_20d| ≤ 2       → SIDEWAYS   (20 phiên đi ngang, đè trước; chống rung
#                                     khi m2 lượn quanh 0 trong thị trường phẳng)
#   m2 > 0              → UPTREND    (tổng 2 phiên còn dương)
#   m2 ≤ 0 & hôm nay >0 → RECOVERY   (hồi: hôm nay xanh nhưng chưa bù cú giảm)
#   m2 ≤ 0 & hôm nay ≤0 → DOWNTREND  (giảm tiếp)
# DEEP_DOWN KHÔNG sinh từ index — chỉ đến từ breadth (classify_regime_breadth)
# qua more_bearish(): VNINDEX đơn dễ bị vài mã lớn kéo, breadth cả rổ đáng tin
# hơn để gọi "sập thật". Ví dụ khớp yêu cầu:
#   qua+10 nay-7  → m2=+3 (giảm) → UPTREND     (vẫn tăng)
#   qua+10 nay-14 → m2=-4 (giảm) → DOWNTREND
#   qua-10 nay+5  → m2=-5 (tăng) → RECOVERY    (hồi, chưa đủ)
#   qua-10 nay+11 → m2=+1 (tăng) → UPTREND
TH_SIDEWAYS_C20 = 2.0   # |chg_20d| ≤ 2% → SIDEWAYS (= |TH_DOWN_C20|, không bịa số mới)


def classify_regime_op2(m2: float | None, today: float | None,
                        chg_20d: float | None) -> dict:
    """Regime Op1 (dấu-m2), live mỗi run. Không EMA, không ngưỡng độ lớn.
    m2 = đà hôm qua + đà hôm nay (có dấu). today = đà hôm nay (chg_pct live).
    Trả {"regime_raw", "reason", "crash_rule"}. DEEP_DOWN đến từ breadth."""
    _m2  = m2      if m2      is not None else 0.0
    _td  = today   if today   is not None else 0.0
    _c20 = chg_20d if chg_20d is not None else 0.0

    if abs(_c20) <= TH_SIDEWAYS_C20:
        return {"regime_raw": "SIDEWAYS",
                "reason": f"c20={_c20:+.2f} trong +-{TH_SIDEWAYS_C20} (di ngang)",
                "crash_rule": False}
    if _m2 > 0:
        return {"regime_raw": "UPTREND",
                "reason": f"m2={_m2:+.2f}>0", "crash_rule": False}
    if _td > 0:
        return {"regime_raw": "RECOVERY",
                "reason": f"m2={_m2:+.2f}<=0 & hom_nay={_td:+.2f}>0 (hoi chua xac nhan)",
                "crash_rule": False}
    return {"regime_raw": "DOWNTREND",
            "reason": f"m2={_m2:+.2f}<=0 & hom_nay={_td:+.2f}<=0", "crash_rule": False}


def classify_regime(close: float, ema50: float, ema200: float | None,
                    chg_5d: float | None, chg_20d: float | None) -> dict:
    """
    Phân loại regime v4.2 RAW (chưa hysteresis) từ snapshot 1 thời điểm.
    Pure function — không I/O, dùng chung cho production + diagnostic.
    Trả {"regime_raw": str, "reason": str}.
    """
    above_50  = close > ema50
    above_200 = (close > ema200) if ema200 is not None else above_50
    c5  = chg_5d  if chg_5d  is not None else 0.0
    c20 = chg_20d if chg_20d is not None else 0.0

    crash = c20 <= TH_CRASH_20D
    if ((not above_50) and (not above_200) and c5 <= TH_DEEP_C5) or crash:
        return {"regime_raw": "DEEP_DOWN",
                "reason": ("crash c20<=-8" if crash
                           else "duoi 2 EMA & c5<=0"),
                "crash_rule": crash}
    if (not above_50) and c5 >= TH_RECOVERY_C5:
        return {"regime_raw": "RECOVERY",
                "reason": f"duoi EMA50 & c5={c5:+.2f}>=+2",
                "crash_rule": False}
    if (not above_50) and (c20 <= TH_DOWN_C20 or c5 <= TH_DOWN_C5):
        return {"regime_raw": "DOWNTREND",
                "reason": "duoi EMA50 & momentum am",
                "crash_rule": False}
    if above_50 and above_200 and c20 > 0:
        return {"regime_raw": "UPTREND",
                "reason": "tren 2 EMA & c20>0",
                "crash_rule": False}
    return {"regime_raw": "SIDEWAYS", "reason": "con lai",
            "crash_rule": False}


def apply_hysteresis(raw: str, crash_rule: bool,
                     prev_effective: str | None,
                     prev_session_raw: str | None) -> dict:
    """
    Hysteresis 2-phiên, bất đối xứng (crash vào DEEP_DOWN = ngay).

    raw               : label raw phiên hiện tại
    crash_rule        : True nếu raw=DEEP_DOWN do chg_20d ≤ −8
    prev_effective    : state hiệu lực gần nhất (từ log); None = bootstrap
    prev_session_raw  : raw label ở entry CUỐI của PHIÊN TRƯỚC (khác ngày);
                        None = chưa có phiên trước trong log

    Trả {"regime_effective": str, "pending": str|None, "note": str}
    """
    # Bootstrap: chưa có lịch sử → nhận raw ngay
    if prev_effective is None:
        return {"regime_effective": raw, "pending": None,
                "note": "bootstrap"}
    # Không đổi
    if raw == prev_effective:
        return {"regime_effective": raw, "pending": None, "note": "hold"}
    # Crash rule: risk control chuyển ngay, không chờ xác nhận
    if raw == "DEEP_DOWN" and crash_rule:
        return {"regime_effective": "DEEP_DOWN", "pending": None,
                "note": "crash-rule fast-in"}
    # Cần xác nhận: raw hôm nay phải trùng raw cuối phiên trước
    if prev_session_raw == raw:
        return {"regime_effective": raw, "pending": None,
                "note": f"confirmed {CONFIRM_SESSIONS} sessions"}
    return {"regime_effective": prev_effective, "pending": raw,
            "note": f"pending confirm ({raw})"}


# ─────────────────────────────────────────────────────────────────────
# SHADOW UPDATE — dùng chung cho step3_context + step_context_refresh
# (I/O qua utils.cache; log commit mỗi run → user review được từng run)
# ─────────────────────────────────────────────────────────────────────
SHADOW_LOG_PATH = "market/regime_v42_log.json"
SHADOW_LOG_CAP  = 600   # ~3 tháng × 7 run/ngày, đủ review + hysteresis


def shadow_update(trend: dict) -> dict:
    """
    Nhận dict trend (từ _vnindex_trend/_fetch_vnindex_trend), tính regime
    ứng viên v4.2 + hysteresis từ log đã lưu, append log, trả các field shadow
    để merge vào context record. KHÔNG đụng market_regime (v2) production.

    Trả:
      market_regime_v42      — state hiệu lực (sau hysteresis)
      market_regime_v42_raw  — state raw phiên/run hiện tại
      regime_v42_pending     — state chờ xác nhận (None nếu không)
      regime_display_hint   — chuỗi hiển thị cho dashboard (Option 1)
    """
    from utils.cache import load_json, save_json
    from utils.helpers import now_ict

    close = trend.get("vnindex_close")
    e50   = trend.get("vnindex_ema50")
    if close is None or e50 is None:
        return {}
    e200 = trend.get("vnindex_ema200")
    c5   = trend.get("vnindex_chg_5d")
    c20  = trend.get("vnindex_chg_20d")

    cand = classify_regime(float(close), float(e50),
                           None if e200 is None else float(e200), c5, c20)

    # ── đọc log để lấy state hysteresis ──
    logdata = load_json(SHADOW_LOG_PATH)
    if not isinstance(logdata, list):
        logdata = []
    today = now_ict().strftime("%Y-%m-%d")
    prev_effective = logdata[-1]["eff"] if logdata else None
    prev_session_raw = None
    for entry in reversed(logdata):
        if entry.get("date") != today:
            prev_session_raw = entry.get("raw")
            break

    h = apply_hysteresis(cand["regime_raw"], cand.get("crash_rule", False),
                         prev_effective, prev_session_raw)

    # ── display hint (Option 1): regime đang dùng + đà 5 phiên + nhãn v4.2 ──
    now_label = trend.get("market_regime", "UNKNOWN")
    momo = ""
    if c5 is not None:
        momo = (f" · hồi {c5:+.1f}%/5p" if c5 > 0
                else f" · {c5:+.1f}%/5p")
    hint = f"{now_label}{momo}"
    if h["regime_effective"] != now_label:
        hint += f" | v4.2: {h['regime_effective']}"
    if h["pending"]:
        hint += f" (chờ xác nhận {h['pending']})"

    # ── append log (cap). Key: regime_now = regime đang chạy production;
    #    raw/eff = ứng viên v4.2 (thô / sau hysteresis). ──
    logdata.append({
        "date": today,
        "time": now_ict().strftime("%H:%M"),
        "close": close, "c5": c5, "c20": c20,
        "regime_now": now_label,
        "raw": cand["regime_raw"],
        "eff": h["regime_effective"],
        "pending": h["pending"],
        "note": h["note"],
        "reason": cand["reason"],
    })
    save_json(SHADOW_LOG_PATH, logdata[-SHADOW_LOG_CAP:])

    return {
        "market_regime_v42"     : h["regime_effective"],
        "market_regime_v42_raw" : cand["regime_raw"],
        "regime_v42_pending"    : h["pending"],
        "regime_display_hint"   : hint,
    }


# ══════════════════════════════════════════════════════════════════════
# V4.5 — REGIME BREADTH-AWARE (chống méo VNINDEX cap-weighted: vài mã lớn
# kéo chỉ số trong khi đa số cổ phiếu yếu). Dùng LẠI NGUYÊN các ngưỡng TH_*
# ở trên (calibrate-safe, KHÔNG thêm tham số mới) — chỉ thay input VNINDEX
# bằng breadth của rổ: "mã trung vị trên/dưới EMA" thay cho "index trên/dưới".
# ══════════════════════════════════════════════════════════════════════

def classify_regime_breadth(share_50: float, share_200: float,
                            med_c5: float | None, med_c20: float | None) -> dict:
    """Phân loại regime từ BREADTH (dùng chung logic classify_regime).
    share_50/200 = tỉ lệ mã có giá > EMA50/EMA200 (0..1). Ngưỡng 0.5 = 'mã
    trung vị trên/dưới EMA' — bản sao breadth của boolean index.
    med_c5/med_c20 = median % thay đổi 5d/20d của rổ."""
    above_50  = share_50  >= 0.5
    above_200 = share_200 >= 0.5
    c5  = med_c5  if med_c5  is not None else 0.0
    c20 = med_c20 if med_c20 is not None else 0.0
    crash = c20 <= TH_CRASH_20D
    if ((not above_50) and (not above_200) and c5 <= TH_DEEP_C5) or crash:
        return {"regime_raw": "DEEP_DOWN",
                "reason": ("breadth crash c20<=-8" if crash
                           else "breadth duoi 2 EMA & c5<=0"),
                "crash_rule": crash}
    if (not above_50) and c5 >= TH_RECOVERY_C5:
        return {"regime_raw": "RECOVERY",
                "reason": f"breadth duoi EMA50 & c5={c5:+.2f}>=+2",
                "crash_rule": False}
    if (not above_50) and (c20 <= TH_DOWN_C20 or c5 <= TH_DOWN_C5):
        return {"regime_raw": "DOWNTREND",
                "reason": "breadth duoi EMA50 & momentum am",
                "crash_rule": False}
    if above_50 and above_200 and c20 > 0:
        return {"regime_raw": "UPTREND",
                "reason": "breadth tren 2 EMA & c20>0",
                "crash_rule": False}
    return {"regime_raw": "SIDEWAYS", "reason": "breadth con lai",
            "crash_rule": False}


# Thứ tự BI QUAN (dùng cho blend "lấy bên xấu hơn")
REGIME_BEARISHNESS = {"UPTREND": 0, "SIDEWAYS": 1, "RECOVERY": 2,
                      "DOWNTREND": 3, "DEEP_DOWN": 4}


def more_bearish(a: str, b: str) -> str:
    """Trả regime BI QUAN hơn trong 2 cái. UNKNOWN bị bỏ qua (lấy cái còn lại).
    Dùng để blend index-regime với breadth-regime: KHÔNG BAO GIỜ lạc quan hơn
    index → an toàn cho sàng lọc (tránh BUY sai khi index bị vài mã lớn che)."""
    if a == "UNKNOWN":
        return b
    if b == "UNKNOWN":
        return a
    ra = REGIME_BEARISHNESS.get(a, 1)
    rb = REGIME_BEARISHNESS.get(b, 1)
    return a if ra >= rb else b
