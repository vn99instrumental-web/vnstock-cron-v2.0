#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_intraday_source_probe.py — ĐO (không đoán) tác động của vnstock_data v3.2.9
lên dữ liệu khớp lệnh trong phiên (intraday).

Mục tiêu trả lời 3 câu hỏi bằng SỐ THẬT trên tài khoản/môi trường của chính repo:
  (1) Nguồn VCI có thật sự bị chặn còn ~100 bản ghi/lượt gọi không?
      → so số dòng trả về khi xin page_size=10000 giữa VCI và KBS/VND/MAS.
  (2) Mỗi nguồn trả nhãn match_type là gì? ("Buy/Sell" tiếng Anh hay "Mua/Bán"
      tiếng Việt, có ATO/ATC/PLO không) → quyết định bộ phân loại mua/bán (B).
  (3) Cột & kiểu dữ liệu (đặc biệt 'time' có múi giờ chưa) — để biết code hiện
      tại còn khớp không.

An toàn:
  - CHỈ ĐỌC. Không ghi/không sửa file production, không đụng ledger.
  - LUÔN exit 0 (không làm gãy debug.yml).
  - stdlib cho phần xử lý; chỉ phụ thuộc vnstock_data.Quote như production.
  - Ghi kết quả JSON có cấu trúc: output/diag_intraday_source_probe.json
"""

import os
import sys
import json
import time
import traceback
from collections import Counter

# ── Nguồn & mã để dò. Vài mã thanh khoản cao (tape dày → dễ lộ trần 100). ──
SOURCES = ["VCI", "KBS", "VND", "MAS"]
SYMBOLS = ["ACB", "HPG", "SSI", "FPT", "VIC"]
PAGESIZE = int(os.environ.get("PROBE_PAGESIZE", "10000"))

OUT_PATH = os.environ.get(
    "PROBE_OUT", os.path.join("output", "diag_intraday_source_probe.json")
)

# Token nhận diện chiều lệnh (chuẩn hoá lowercase, bỏ dấu trước khi so).
BUY_TOKENS = ("buy", "mua")
SELL_TOKENS = ("sell", "ban")


def _norm(x):
    """lowercase + bỏ dấu tiếng Việt để 'Bán'/'Ban'/'BÁN' về cùng 'ban'."""
    import unicodedata
    if not isinstance(x, str):
        return ""
    x = unicodedata.normalize("NFD", x)
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return x.lower().strip()


def _fetch(src, sym):
    """Gọi intraday cho (src, sym). Trả (df, meta, err).
    Thử page_size= trước (như production); nếu kwarg không còn → thử intraday()."""
    from vnstock_data import Quote
    meta = {"used_kwarg": None}
    # cách 1: y hệt production
    try:
        df = Quote(source=src, symbol=sym).intraday(page_size=PAGESIZE)
        meta["used_kwarg"] = f"page_size={PAGESIZE}"
        return df, meta, None
    except TypeError as e:
        # có thể page_size đã bị bỏ ở API mới → thử không tham số
        meta["page_size_typeerror"] = str(e)
    except Exception as e:
        return None, meta, f"{type(e).__name__}: {e}"
    # cách 2: fallback không tham số
    try:
        df = Quote(source=src, symbol=sym).intraday()
        meta["used_kwarg"] = "none"
        return df, meta, None
    except Exception as e:
        return None, meta, f"{type(e).__name__}: {e}"


def _describe(df):
    """Rút đặc trưng của 1 dataframe intraday — không in cả bảng."""
    import pandas as pd  # vnstock_data đã kéo pandas
    info = {
        "rows": int(len(df)),
        "columns": list(map(str, df.columns)),
        "has_match_type": "match_type" in df.columns,
        "has_time": "time" in df.columns,
        "has_price": "price" in df.columns,
        "has_volume": "volume" in df.columns,
    }
    # time dtype + tz
    if "time" in df.columns:
        info["time_dtype"] = str(df["time"].dtype)
        info["time_is_tz_aware"] = bool(getattr(df["time"].dtype, "tz", None) is not None)
    # match_type: nhãn duy nhất + đếm
    if "match_type" in df.columns:
        vc = Counter(df["match_type"].astype("object").tolist())
        # top 12 nhãn
        info["match_type_values"] = {
            str(k): int(v) for k, v in vc.most_common(12)
        }
        norm_series = df["match_type"].astype("object").map(_norm)
        buy = norm_series.map(lambda t: any(k in t for k in BUY_TOKENS))
        sell = norm_series.map(lambda t: any(k in t for k in SELL_TOKENS))
        neither = (~buy) & (~sell)
        info["side_match"] = {
            "buy_rows": int(buy.sum()),
            "sell_rows": int(sell.sum()),
            "neither_rows": int(neither.sum()),  # ATO/ATC/PLO/không rõ chiều
        }
        # buy_ratio theo KHỐI LƯỢNG (y cách production)
        if "volume" in df.columns:
            v = pd.to_numeric(df["volume"], errors="coerce")
            bv = float(v[buy].sum())
            sv = float(v[sell].sum())
            tot = bv + sv
            info["buy_ratio_by_volume"] = round(bv / tot, 4) if tot > 0 else None
            info["total_volume"] = float(v.sum(skipna=True))
    return info


def _pkg_version():
    """Ghi lại ĐANG ĐO trên vnstock_data phiên bản nào (khỏi nhầm 3.2.8 vs 3.2.9)."""
    try:
        import importlib.metadata as md
        return md.version("vnstock_data")
    except Exception:
        try:
            import vnstock_data
            return getattr(vnstock_data, "__version__", "unknown")
        except Exception:
            return "unknown"


def main():
    started = time.time()
    report = {
        "probe": "intraday_source_probe",
        "vnstock_data_version": _pkg_version(),
        "pagesize_requested": PAGESIZE,
        "sources": SOURCES,
        "symbols": SYMBOLS,
        "results": [],
        "conclusions": {},
    }

    # In NGAY version đang đo (để log tự tố cáo 3.2.8 hay 3.2.9)
    print(f"vnstock_data_version = {report['vnstock_data_version']}  "
          f"| page_size xin = {PAGESIZE}\n")

    # rows + ĐỘ TRỄ trung bình theo nguồn (elapsed = manh mối phân trang)
    rows_by_source = {s: [] for s in SOURCES}
    elapsed_by_source = {s: [] for s in SOURCES}

    for src in SOURCES:
        for sym in SYMBOLS:
            row = {"source": src, "symbol": sym}
            t0 = time.time()
            df, meta, err = _fetch(src, sym)
            row["elapsed_s"] = round(time.time() - t0, 2)
            row.update(meta)
            if err is None:
                elapsed_by_source[src].append(row["elapsed_s"])
            if err is not None:
                row["error"] = err
                row["rows"] = None
            elif df is None or getattr(df, "empty", True):
                row["rows"] = 0
                row["empty"] = True
            else:
                try:
                    row.update(_describe(df))
                    rows_by_source[src].append(row["rows"])
                except Exception as e:
                    row["describe_error"] = f"{type(e).__name__}: {e}"
            report["results"].append(row)
            # in gọn từng dòng cho log debug.yml
            print(
                f"[{src:>3}] {sym:>4}  rows={row.get('rows')}  "
                f"elapsed={row.get('elapsed_s')}s  "
                f"kwarg={row.get('used_kwarg')}  "
                f"tz={row.get('time_is_tz_aware')}  "
                f"labels={list((row.get('match_type_values') or {}).keys())[:5]}  "
                f"{'ERR:' + row['error'] if 'error' in row else ''}"
            )
            time.sleep(0.4)  # nhẹ tay với API

    # ── Kết luận tự động (chỉ mô tả số, không phán) ──
    for s in SOURCES:
        vals = rows_by_source[s]
        el = elapsed_by_source[s]
        report["conclusions"][s] = {
            "n_ok": len(vals),
            "rows_min": min(vals) if vals else None,
            "rows_max": max(vals) if vals else None,
            "rows_avg": round(sum(vals) / len(vals), 1) if vals else None,
            # cờ nghi trần 100: mọi mã đều <=110 dòng
            "suspect_100_cap": bool(vals) and max(vals) <= 110,
            # ĐỘ TRỄ mỗi lượt gọi — cao bất thường = dấu hiệu phân trang nhiều HTTP
            "elapsed_min": round(min(el), 2) if el else None,
            "elapsed_max": round(max(el), 2) if el else None,
            "elapsed_avg": round(sum(el) / len(el), 2) if el else None,
        }

    report["elapsed_total_s"] = round(time.time() - started, 1)

    try:
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n✅ Đã ghi {OUT_PATH}")
    except Exception as e:
        print(f"\n⚠️ Không ghi được {OUT_PATH}: {e}")

    print(f"\n=== TÓM TẮT THEO NGUỒN (vnstock_data {report['vnstock_data_version']}) ===")
    for s in SOURCES:
        c = report["conclusions"][s]
        print(f"  {s:>3}: n_ok={c['n_ok']}  rows_avg={c['rows_avg']}  "
              f"(min={c['rows_min']} max={c['rows_max']})  "
              f"elapsed_avg={c['elapsed_avg']}s  "
              f"(min={c['elapsed_min']} max={c['elapsed_max']})  "
              f"nghi_tran_100={c['suspect_100_cap']}")
    print("\n(elapsed_avg cao bất thường ở 1 nguồn = nguồn đó phân trang nhiều "
          "lượt HTTP → đây là thủ phạm làm prefetch chậm)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        # LUÔN exit 0 để không làm gãy debug.yml
        sys.exit(0)
