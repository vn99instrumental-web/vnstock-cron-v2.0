"""
scripts/diag_ratio_columns.py
==============================
Diagnostic-only. KHÔNG ghi cache, KHÔNG sửa output.

Mục tiêu: dò tên cột THẬT mà ratio_summary() trả về trên live VCI,
so sánh với tên code đang gọi, xác nhận get_any() alias resolution
cho EPS / BVPS / beta / interest_coverage.

Chạy qua debug.yml:
  scripts/diag_ratio_columns.py

Override mã mẫu:
  DIAG_SYMBOL=VCB (mặc định ACB + thêm HPG, VCB)
"""
import os
import sys
import time
from importlib import metadata

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"
os.environ["MPLCONFIGDIR"] = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock", exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd

# ── Helpers ──────────────────────────────────────────────────────────
def pkg_version(name):
    try:
        return metadata.version(name)
    except Exception:
        return "NOT INSTALLED"


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def safe_ratio(symbol, source="VCI"):
    """Gọi ratio_summary() với retry đơn giản."""
    from vnstock_data import Company
    for attempt in range(3):
        try:
            df = Company(source=source, symbol=symbol).ratio_summary()
            return df
        except Exception as e:
            print(f"  ⚠️ ratio_summary({symbol}) attempt {attempt+1}: {e}")
            time.sleep(2)
    return None


# ── Tên cột code đang dùng (trước fix) vs alias mới ──────────────
CODE_NAMES = {
    # key: tên code gọi get("xxx")
    # value: list alias get_any() sẽ thử (theo thứ tự)
    "eps":                ["eps", "eps_co_ban", "trailing_eps"],
    "bvps":               ["bvps", "gia_tri_so_sach_mot_co_phieu",
                           "book_value_per_share_bvps"],
    "beta":               ["beta", "he_so_beta"],
    "interest_coverage":  ["interest_coverage",
                           "kha_nang_thanh_toan_lai_vay"],
    # Các cột đang CHẠY TỐT — kiểm để xác nhận alias ngắn còn sống:
    "pe":                 ["pe", "p_e_co_ban"],
    "pb":                 ["pb", "p_b"],
    "roe":                ["roe"],
    "roa":                ["roa"],
    "dividend_yield":     ["dividend_yield", "ty_suat_co_tuc"],
    "gross_margin":       ["gross_margin", "bien_loi_nhuan_gop"],
    "after_tax_profit_margin": ["after_tax_profit_margin",
                                "bien_loi_nhuan_rong"],
    "quick_ratio":        ["quick_ratio",
                           "ty_suat_thanh_toan_nhanh"],
    "ev_to_ebitda":       ["ev_to_ebitda", "ev_ebitda"],
}

# ── Main ─────────────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("  diag_ratio_columns — dò tên cột ratio_summary() trên live VCI")
    print("=" * 72)

    # Package versions
    for pkg in ["vnstock", "vnstock_data"]:
        print(f"  {pkg}: {pkg_version(pkg)}")

    # Symbols to probe
    extra = os.environ.get("DIAG_SYMBOL", "").strip().upper()
    symbols = ["ACB", "HPG", "VCB"]
    if extra and extra not in symbols:
        symbols.insert(0, extra)

    for sym in symbols:
        print(f"\n{'─'*72}")
        print(f"  SYMBOL: {sym}")
        print(f"{'─'*72}")
        time.sleep(0.5)

        df = safe_ratio(sym)
        if df is None or df.empty:
            print(f"  ❌ ratio_summary({sym}) trả DataFrame rỗng/None")
            continue

        cols = sorted(df.columns.tolist())
        print(f"\n  📋 Tổng cột: {len(cols)}")
        print(f"  Columns: {cols}\n")

        # Lấy dòng mới nhất
        row = df.iloc[-1]

        print(f"  {'code get()':28s} | {'tên cũ':5s} | {'tên tìm được':34s} | {'giá trị':>12s}")
        print(f"  {'-'*28}-+-{'-'*5}-+-{'-'*34}-+-{'-'*12}")

        for code_name, aliases in CODE_NAMES.items():
            # Thử tên gốc (code cũ)
            old_hit = code_name in df.columns
            # get_any: thử lần lượt
            found_alias = None
            found_val = None
            for a in aliases:
                if a in df.columns:
                    v = _num(row.get(a))
                    if v is not None:
                        found_alias = a
                        found_val = v
                        break
            status = "✅" if found_alias else "❌"
            old_mark = "✅" if old_hit else "❌"
            val_str = f"{found_val}" if found_val is not None else "None"
            alias_str = found_alias or "(không thấy)"
            print(f"  {code_name:28s} | {old_mark:5s} | {status} {alias_str:31s} | {val_str:>12s}")

        # Tìm cột chứa keyword eps/bvps/beta/interest mà CHƯA NẰM trong alias list
        all_aliases = set()
        for als in CODE_NAMES.values():
            all_aliases.update(als)
        interesting_kw = ["eps", "bvps", "beta", "interest", "book", "earning"]
        unlisted = [c for c in cols if any(k in c.lower() for k in interesting_kw)
                    and c not in all_aliases]
        if unlisted:
            print(f"\n  ⚠️ Cột CÓ keyword nhưng CHƯA trong alias list:")
            for c in unlisted:
                print(f"     {c} = {_num(row.get(c))}")

        time.sleep(1.0)  # tránh rate limit giữa các symbol

    print(f"\n{'='*72}")
    print("  DONE — copy output này gửi lại để xác nhận tên cột đúng")
    print(f"{'='*72}")


if __name__ == "__main__":
    main()
