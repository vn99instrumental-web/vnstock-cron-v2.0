#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_ff_intra_units.py — READ-ONLY. Chạy qua debug.yml.

Mục tiêu: XÁC NHẬN đơn vị của các field price_board trước khi patch ff_intraday.
Demo live 07/08 cho thấy r = net/accumulated_value nổ ~1e6× → nghi accumulated_value
ở đơn vị TRIỆU đồng còn foreign_*_value ở đơn vị ĐỒNG. Diag này kiểm trực tiếp, không đoán.

Cross-check dùng khối lượng (không phụ thuộc giả định đơn vị):
  - foreign_buy_value / foreign_buy_volume  ≈ giá 1 cp  → xác nhận foreign value = VND
  - accumulated_value  vs  accumulated_volume × giá     → suy ra hệ số đơn vị của accumulated_value
Đồng thời in TẤT CẢ cột chứa value/volume/price để soi có cột GTGD chuẩn hơn không.
"""
import logging, math
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("diag_ff_units")

from vnstock.explorer.vci import Trading

SYMS = ["HPG", "VCB", "VIC"]


def _find(cols, *subs):
    """cột đầu tiên chứa TẤT CẢ substrings (ưu tiên có tiền tố match.)."""
    subs = [s.lower() for s in subs]
    cands = [c for c in cols if all(s in c.lower() for s in subs)]
    cands.sort(key=lambda c: (0 if "match" in c.lower() else 1, len(c)))
    return cands[0] if cands else None


def main():
    df = Trading(source="VCI").price_board(SYMS)
    if hasattr(df, "columns") and hasattr(df.columns, "to_flat_index"):
        df.columns = [".".join([str(x) for x in t if x != ""]) if isinstance(t, tuple) else str(t)
                      for t in df.columns.to_flat_index()]
    cols = list(df.columns)

    log.info("=== TẤT CẢ cột có 'value' / 'volume' / 'price' ===")
    for c in cols:
        cl = c.lower()
        if any(k in cl for k in ("value", "volume", "price")):
            log.info("   %s", c)

    c_sym  = _find(cols, "symbol") or _find(cols, "ticker")
    c_fbv  = _find(cols, "foreign_buy_value")
    c_fsv  = _find(cols, "foreign_sell_value")
    c_fbvol= _find(cols, "foreign_buy_volume")
    c_fsvol= _find(cols, "foreign_sell_volume")
    c_acv  = _find(cols, "accumulated_value")
    c_acvol= _find(cols, "accumulated_volume")
    c_px   = _find(cols, "match_price") or _find(cols, "match", "price") \
             or _find(cols, "reference_price") or _find(cols, "close") or _find(cols, "basic_price")

    log.info("cols dùng: sym=%s fbv=%s fsv=%s fb_vol=%s acc_val=%s acc_vol=%s px=%s",
             c_sym, c_fbv, c_fsv, c_fbvol, c_acv, c_acvol, c_px)

    log.info("-" * 100)
    for _, row in df.iterrows():
        sym = str(row.get(c_sym)) if c_sym else "?"
        if sym not in SYMS:
            continue

        def g(c):
            try:
                v = row.get(c)
                return float(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None
            except Exception:
                return None

        fbv, fsv = g(c_fbv), g(c_fsv)
        fbvol    = g(c_fbvol)
        acv, acvol, px = g(c_acv), g(c_acvol), g(c_px)
        net = (fbv - fsv) if (fbv is not None and fsv is not None) else None

        log.info("### %s", sym)
        log.info("   raw: foreign_buy_value=%s  foreign_sell_value=%s  net=%s", fbv, fsv, net)
        log.info("   raw: accumulated_value=%s  accumulated_volume=%s  price=%s", acv, acvol, px)

        # 1) đơn vị foreign value: value/volume ≈ giá?
        if fbv and fbvol:
            log.info("   check foreign: buy_value/buy_volume = %.2f  (≈ giá 1cp nếu value=VND)", fbv / fbvol)

        # 2) đơn vị accumulated_value: so với volume×giá
        if acvol and px:
            gtgd_vol = acvol * px
            log.info("   check GTGD: accumulated_volume×price = %.3e VND", gtgd_vol)
            if acv:
                log.info("             accumulated_value(raw)      = %.3e  → hệ số = vol×px / raw = %.1f",
                         acv, gtgd_vol / acv if acv else float("nan"))

        # 3) ratio dưới 2 giả định đơn vị
        if net is not None and acv:
            r_raw  = net / acv
            r_1e6  = net / (acv * 1e6)
            log.info("   r(raw)   = %+.2f%%   [nếu accumulated_value cùng đơn vị VND]", r_raw * 100)
            log.info("   r(×1e6)  = %+.2f%%   [nếu accumulated_value ở TRIỆU đồng]", r_1e6 * 100)
        log.info("-" * 100)

    log.info("KẾT LUẬN cần rút: cột nào là GTGD đúng, và hệ số đơn vị để net & GTGD cùng đơn vị.")
    log.info("=== DONE ===")


if __name__ == "__main__":
    main()
