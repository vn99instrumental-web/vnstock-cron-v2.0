#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/demo_ff_intraday.py — DEMO tín hiệu "khối ngoại trong phiên / tổng GTGD"
================================================================================
In r + điểm shadow cho vài mã, dùng ĐÚNG helper utils/ff_intraday.py mà pipeline
sẽ dùng → xem tín hiệu chạy thật trước khi tin vào ledger.

⚠️ CHẠY TRONG GIỜ GD (09:15–14:30 ICT). Càng về chiều (frac lớn) số càng ổn định.

TRIGGER:
    Actions → debug.yml → Run workflow → script = scripts/demo_ff_intraday.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
from utils.ff_intraday import (fetch_intraday_ff, session_fraction, score_ff_intra,
                               FRAC_GATE, DEADBAND, X_MOD, X_STRONG, CAP)
from utils.helpers import now_ict, is_market_open

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYMS = ["HPG", "VCB", "SSI", "FPT", "VND", "MSN", "MWG", "VIC", "VHM", "STB"]


def _bil(v):
    try:
        return f"{v/1e9:+.2f}tỷ"
    except Exception:
        return "?"


if __name__ == "__main__":
    now = now_ict()
    frac = session_fraction(now)
    log.info(f"=== DEMO FF-INTRADAY ({now:%Y-%m-%d %H:%M} ICT) ===")
    log.info(f"Market open: {is_market_open()} | session_fraction f={frac} "
             f"(gate {FRAC_GATE}: {'ĐÃ QUA → chấm' if (frac or 0) >= FRAC_GATE else 'CHƯA → điểm sẽ =0'})")
    log.info(f"Ngưỡng PRE-REGISTER: deadband={DEADBAND:.0%} | X_mod={X_MOD:.0%} "
             f"| X_strong={X_STRONG:.0%} | cap=±{CAP}")

    ffi = fetch_intraday_ff(SYMS)
    log.info("-" * 78)
    log.info(f"{'Mã':<6}{'net ngoại':>12}{'tổng GTGD':>13}{'r=net/GTGD':>13}{'điểm shadow':>14}")
    for s in SYMS:
        d = ffi.get(s)
        if not d:
            log.info(f"{s:<6}{'(no data)':>12}")
            continue
        r = d.get("ff_intra_ratio")
        pts, lbl = score_ff_intra(r, frac)
        rtxt = f"{r:+.2%}" if r is not None else "—"
        log.info(f"{s:<6}{_bil(d.get('ff_intra_net')):>12}"
                 f"{d.get('ff_intra_gtgd', 0)/1e9:>11.1f}tỷ{rtxt:>13}{pts:>+14d}")
    log.info("-" * 78)
    log.info("Đọc: r>0 = ngoại đang mua ròng chiếm % dòng tiền; điểm shadow chỉ để")
    log.info("     ghi ledger đối chiếu outcome — CHƯA vào decision (cap=0 trong scoring).")
    log.info("=== DONE ===")
