#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils/ff_intraday.py — Khối ngoại TRONG PHIÊN / tổng GTGD  (SHADOW factor)
=========================================================================
Nguồn: Trading(source="VCI").price_board(list) — verified 2026-08-07 (diag_ff_intra_units):
  match.foreign_buy_value / match.foreign_sell_value → net ngoại tích luỹ TRONG phiên
      ĐƠN VỊ: ĐỒNG (VND). Xác nhận: buy_value/buy_volume ≈ giá cp (HPG 22.029 ~ 22.100…).
  match.accumulated_value                            → tổng GTGD trong phiên (mẫu số)
      ĐƠN VỊ: TRIỆU ĐỒNG. Xác nhận: (accumulated_volume×price)/accumulated_value ≈ 1.0e6
      cho HPG/VCB/VIC (1.001.883 / 1.008.849 / 998.230). → phải ×1e6 để ra VND.
  (foreign_trade CŨ = EOD T-1; đây là REALTIME — đã verify Δ≠0 giữa 2 lần gọi cách 45s.)

Công thức:  r = (foreign_buy_value − foreign_sell_value) / (accumulated_value × 1e6)
Guard đơn vị: |net| ≤ tổng GTGD (ngoại là tập con của tổng khớp) → |r|>1 là BẤT KHẢ
             → coi là lỗi đơn vị/dữ liệu, trả None (không ghi ledger rác).

TRẠNG THÁI = SHADOW. score_ff_intra() chỉ để GHI ledger đối chiếu outcome sau —
ngưỡng X + cap ở đây là PRE-REGISTER (chưa tối ưu), CHƯA vào quyết định.
Khi đủ outcome: bucket r vs forward return (tách theo liquidity tier) → chốt X + cap.

Dùng chung bởi: v2f_step_snapshot.py (gắn metadata) + scripts/demo_ff_intraday.py.
KHÔNG import gì từ steps/* để tránh vòng phụ thuộc.
"""
from __future__ import annotations
import time

# ── Ngưỡng PRE-REGISTER (chưa tối ưu — chờ forward outcome) ──────────────
FRAC_GATE = 0.35    # phiên trôi < 35% (~trước 10:30) → mẫu số quá nhỏ → bỏ (0)
DEADBAND  = 0.02    # |r| < 2%  → coi như cân bằng (0)
X_MOD     = 0.03    # |r| ≥ 3%  → vừa
X_STRONG  = 0.08    # |r| ≥ 8%  → mạnh
CAP       = 4       # trần shadow (nhỏ; cap thật do IC hold-out quyết)

# ── Cờ "NN gom mạnh" (PRE-REGISTER, dùng cho HIGHLIGHT + cộng điểm V4) ──────
# Cố định, KHÔNG fit data. 3 điều kiện: mua ròng + đủ đậm (%) + tiền thật (tỷ).
FLAG_X       = 0.08       # |net/GTGD| ≥ 8%   (độ áp đảo so với dòng tiền mã)
FLAG_NET_VND = 10e9       # |net| ≥ 10 tỷ     (tiền thật — cửa lọc thanh khoản)
FLAG_CAP     = 3          # điểm cộng/trừ khi cờ bật (chỉ V4)

# Đơn vị: accumulated_value (price_board VCI) ở TRIỆU đồng → nhân để ra VND.
GTGD_UNIT_TO_VND = 1_000_000


def session_fraction(now) -> float | None:
    """f ∈ [0,1] = phần phiên GD đã trôi.
    Phiên liên tục: 09:15–11:30 (135') + 13:00–14:30 (90') = 225'.
    Nghỉ trưa 11:30–13:00 → f giữ nguyên 0.6. Trước 09:15 → 0; sau 14:30 → 1."""
    try:
        mins = now.hour * 60 + now.minute
    except Exception:
        return None
    OPEN, LUNCH_S, LUNCH_E, CLOSE = 9 * 60 + 15, 11 * 60 + 30, 13 * 60, 14 * 60 + 30
    MORNING = LUNCH_S - OPEN                 # 135
    TOTAL   = MORNING + (CLOSE - LUNCH_E)    # 225
    if mins <= OPEN:
        return 0.0
    if mins >= CLOSE:
        return 1.0
    if mins <= LUNCH_S:
        elapsed = mins - OPEN
    elif mins <= LUNCH_E:
        elapsed = MORNING
    else:
        elapsed = MORNING + (mins - LUNCH_E)
    return round(elapsed / TOTAL, 4)


def _flatten(df):
    df = df.copy()
    df.columns = [".".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
                  for c in df.columns]
    return df


def _col(cols, suffix):
    for c in cols:
        if str(c).lower().endswith(suffix):
            return c
    return None


def fetch_intraday_ff(symbols, chunk: int = 50) -> dict:
    """Trả {sym: {ff_intra_net, ff_intra_gtgd, ff_intra_ratio}} từ price_board bulk.
    1 lệnh / chunk (mặc định 50 mã) → toàn universe ~3 lệnh, tốn quota không đáng kể.
    Lỗi/rỗng → bỏ qua mã đó (fail-soft), không raise.
    ff_intra_gtgd trả về đã ở ĐỒNG (VND) — đã ×1e6 từ accumulated_value (triệu đồng)."""
    from vnstock_data import Trading

    out: dict = {}
    syms = [s for s in symbols if s]
    for i in range(0, len(syms), chunk):
        batch = syms[i:i + chunk]
        df = None
        for _att in range(3):
            try:
                df = Trading(source="VCI").price_board(batch)
                if df is not None and not df.empty:
                    break
            except Exception:
                df = None
            time.sleep(1.0 * (_att + 1))
        if df is None or df.empty:
            continue

        df = _flatten(df)
        cols = list(df.columns)
        c_sym  = _col(cols, ".symbol") or _col(cols, "symbol")
        c_fbv  = _col(cols, "foreign_buy_value")
        c_fsv  = _col(cols, "foreign_sell_value")
        c_gtgd = _col(cols, ".accumulated_value") or _col(cols, "accumulated_value")
        if not (c_sym and c_fbv and c_fsv and c_gtgd):
            continue

        for _, row in df.iterrows():
            try:
                sym  = str(row.get(c_sym))
                fbv  = float(row.get(c_fbv)  or 0)                       # VND
                fsv  = float(row.get(c_fsv)  or 0)                       # VND
                gtgd = float(row.get(c_gtgd) or 0) * GTGD_UNIT_TO_VND    # triệu → VND
            except (TypeError, ValueError):
                continue
            net   = fbv - fsv
            ratio = (net / gtgd) if gtgd > 0 else None
            # Guard đơn vị: |net| ≤ tổng GTGD → |r|>1 bất khả → lỗi đơn vị/dữ liệu → bỏ.
            if ratio is not None and abs(ratio) > 1.0:
                ratio = None
            out[sym] = {
                "ff_intra_net":   round(net, 0),
                "ff_intra_gtgd":  round(gtgd, 0),
                "ff_intra_ratio": round(ratio, 4) if ratio is not None else None,
            }
    return out


def score_ff_intra(ratio, frac):
    """Điểm SHADOW (chưa vào quyết định). Trả (pts, label).
    Gate phase (frac<0.35 → 0) + dead-band 2 chiều + 2 bậc, đối xứng, cap ±CAP."""
    if ratio is None or frac is None or frac < FRAC_GATE:
        return 0, ""
    a = abs(ratio)
    if a < DEADBAND:
        return 0, f"FFintra r={ratio:+.1%} ~cân bằng"
    sign = 1 if ratio > 0 else -1
    if   a >= X_STRONG: pts = CAP * sign          # ±4
    elif a >= X_MOD:    pts = 2 * sign            # ±2
    else:               pts = 1 * sign            # ±1 (giữa deadband và X_mod)
    return pts, f"FFintra r={ratio:+.1%} f={frac:.2f} {pts:+d}"


def ff_intra_flag(net, ratio, frac):
    """Cờ "NN gom mạnh" (PRE-REGISTER). Trả (flag, pts):
      flag = +1 (NN mua mạnh) / -1 (NN bán mạnh) / 0
      pts  = flag * FLAG_CAP   (±3 / 0)  — CHỈ V4 cộng số này vào score_trade.
    3 điều kiện phải cùng đúng: đúng chiều + |ratio|≥FLAG_X + |net|≥FLAG_NET_VND,
    và phiên đã trôi ≥ FRAC_GATE (mẫu số đủ tin). Đối xứng mua/bán."""
    if net is None or ratio is None or frac is None or frac < FRAC_GATE:
        return 0, 0
    if net > 0 and ratio >= FLAG_X and net >= FLAG_NET_VND:
        return 1, FLAG_CAP
    if net < 0 and ratio <= -FLAG_X and abs(net) >= FLAG_NET_VND:
        return -1, -FLAG_CAP
    return 0, 0
