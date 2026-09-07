# -*- coding: utf-8 -*-
"""
of_side.py — Phân loại CHIỀU lệnh khớp (mua/bán) độc lập với nguồn dữ liệu.

Lý do tồn tại (vnstock_data v3.2.9):
  - Nguồn khớp lệnh có thể trả nhãn tiếng Anh ("Buy"/"Sell", VCI) HOẶC tiếng Việt
    ("Mua"/"Bán chủ động", KBS), và có thêm ATO/ATC/PLO (lệnh định kỳ / không rõ
    chiều). Code cũ chỉ so .str.contains("Buy"/"Sell") → nếu đổi sang KBS sẽ khớp
    RỖNG → buy_ratio về 0/None âm thầm.
  - Helper này chuẩn hoá (bỏ dấu, lowercase) rồi nhận diện theo token, nên KHÔNG
    đổi kết quả khi vẫn dùng VCI (nhãn Anh), nhưng an toàn khi chuyển nguồn.

Hành vi khớp CHÍNH XÁC hành vi cũ với VCI:
  - "Buy"/"BuyUp"... → BUY;  "Sell"/"SellDown"... → SELL
  - ATO/ATC/PLO/ô rỗng/không rõ chiều → KHÔNG tính vào buy lẫn sell (trung tính),
    y như .str.contains cũ (chúng vốn không chứa 'buy'/'sell').
"""

import unicodedata

# Token chiều lệnh (đã chuẩn hoá: lowercase, bỏ dấu). Mở rộng ở đây nếu A phát
# hiện nhãn lạ (vd nguồn nào đó dùng 'b'/'s' một ký tự — KHI ĐÓ mới thêm, có số).
_BUY_TOKENS = ("buy", "mua")
_SELL_TOKENS = ("sell", "ban")   # 'ban' = 'bán' sau khi bỏ dấu


def _norm_one(x) -> str:
    """lowercase + bỏ dấu tiếng Việt: 'Bán'/'BÁN'/'Ban' → 'ban'."""
    if not isinstance(x, str):
        return ""
    x = unicodedata.normalize("NFD", x)
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return x.lower().strip()


def _is_buy(x) -> bool:
    t = _norm_one(x)
    return any(k in t for k in _BUY_TOKENS)


def _is_sell(x) -> bool:
    t = _norm_one(x)
    return any(k in t for k in _SELL_TOKENS)


def buy_sell_masks(match_type_series):
    """
    Nhận cột match_type (pandas Series), trả (buy_mask, sell_mask) kiểu bool Series.
    Dùng thay cho:
        buy_mask  = df["match_type"].str.contains("Buy",  case=False, na=False)
        sell_mask = df["match_type"].str.contains("Sell", case=False, na=False)
    """
    s = match_type_series.astype("object")
    buy = s.map(_is_buy)
    sell = s.map(_is_sell)
    return buy, sell
