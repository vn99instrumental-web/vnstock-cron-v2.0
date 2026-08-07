#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils/ff_intraday.py — Khối ngoại TRONG PHIÊN / tổng GTGD  (SHADOW factor)
=========================================================================
Nguồn: Trading(VCI).price_board(list) — verified 2026-08-07 (diag_intraday_foreign):
  match.foreign_buy_value  / match.foreign_sell_value → net ngoại tích luỹ TRONG phiên
  match.accumulated_value                             → tổng GTGD trong phiên (mẫu số)
  (foreign_trade CŨ = EOD T-1; đây là REALTIME — đã verify Δ≠0 giữa 2 lần gọi cách 45s.)

Công thức:  r = (foreign_buy_value - foreign_sell_value) / accumulated_value

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
    Lỗi/rỗng → bỏ qua mã đó (fail-soft), không raise."""
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
                fbv  = float(row.get(c_fbv)  or 0)
                fsv  = float(row.get(c_fsv)  or 0)
                gtgd = float(row.get(c_gtgd) or 0)
            except (TypeError, ValueError):
                continue
            net   = fbv - fsv
            ratio = (net / gtgd) if gtgd > 0 else None
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
