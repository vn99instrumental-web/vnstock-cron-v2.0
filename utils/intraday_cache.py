"""
utils/intraday_cache.py — Cache tape intraday DÙNG CHUNG trong 1 run
=====================================================================
Ý tưởng (P0.1 + Option B): bước prefetch fetch intraday(page_size=10000) MỘT LẦN
mỗi mã (song song, đã benchmark sạch 429 ở workers=3/interval=0.35), ghi tape ra
đĩa; snapshot và order_flow ĐỌC LẠI tape đó thay vì mỗi bên tự gọi intraday().

Lợi:
  - Bỏ fetch trùng (snapshot intraday(200) + order_flow intraday(10000)).
  - Song song hoá endpoint nặng ở 1 chỗ có kiểm soát → nhanh hơn order_flow đơn luồng.
  - Snapshot & order_flow dùng CÙNG tape / cùng timestamp → nhất quán.

ROLLBACK (an toàn tuyệt đối):
  - Đặt env PREFETCH_ENABLED=0  → mọi consumer bỏ qua cache, fetch LIVE như cũ.
  - Ngay cả khi bật, mỗi consumer VẪN tự fetch live nếu cache miss / sai ngày /
    parquet-pickle lỗi. Không đường nào làm MẤT data — xấu nhất là chậm như cũ.

Lưu trữ:
  - Định dạng pickle (pandas built-in, KHÔNG cần pyarrow) → không thêm dependency.
  - Thư mục mặc định: output/cache/intraday/  (override qua INTRADAY_CACHE_DIR).
  - KHÔNG nằm trong whitelist commit của workflow + có .gitignore → không bị commit.
  - Runner GitHub Actions ephemeral → không có tape sót từ run trước; manifest
    market_date vẫn được kiểm như phòng thủ lớp 2 (chống dùng nhầm tape cũ).
"""
import os
import json
import shutil
import logging

import pandas as pd

log = logging.getLogger(__name__)

# Base dir (override qua env). Theo convention output/cache/ có sẵn (ta_cache.json).
_CACHE_DIR = os.environ.get(
    "INTRADAY_CACHE_DIR",
    os.path.join("output", "cache", "intraday"),
)
_MANIFEST = os.path.join(_CACHE_DIR, "_manifest.json")


def is_enabled() -> bool:
    """Bật/tắt toàn bộ cơ chế prefetch-cache qua env. Mặc định BẬT."""
    return os.environ.get("PREFETCH_ENABLED", "1") == "1"


def cache_dir() -> str:
    return _CACHE_DIR


def _sym_path(symbol: str) -> str:
    return os.path.join(_CACHE_DIR, f"{symbol}.pkl")


# ── Ghi (dùng bởi bước prefetch) ────────────────────────────────────────────
def reset_dir() -> None:
    """Xoá sạch cache cũ đầu mỗi run prefetch → chắc chắn không dùng nhầm tape cũ."""
    try:
        if os.path.isdir(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR, ignore_errors=True)
    except Exception:
        pass
    os.makedirs(_CACHE_DIR, exist_ok=True)


def write_tape(symbol: str, df) -> bool:
    if df is None or getattr(df, "empty", True):
        return False
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        df.to_pickle(_sym_path(symbol))
        return True
    except Exception as e:
        log.warning(f"  intraday_cache write {symbol} fail: {e}")
        return False


def write_manifest(meta: dict) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_MANIFEST, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        log.warning(f"  intraday_cache manifest write fail: {e}")


# ── Đọc (dùng bởi snapshot + order_flow) ────────────────────────────────────
def read_manifest() -> dict | None:
    if not os.path.exists(_MANIFEST):
        return None
    try:
        with open(_MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _manifest_valid(today: str) -> bool:
    m = read_manifest()
    if not m:
        return False
    return m.get("market_date") == today


def read_tape(symbol: str, today: str):
    """
    Trả DataFrame tape nếu TẤT CẢ đúng:
      - PREFETCH_ENABLED, VÀ
      - manifest tồn tại & market_date == hôm nay (không dùng nhầm tape cũ), VÀ
      - file pickle của mã đọc được & không rỗng.
    Ngược lại trả None → caller tự fetch live (fallback an toàn).
    """
    if not is_enabled():
        return None
    if not _manifest_valid(today):
        return None
    p = _sym_path(symbol)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_pickle(p)
        if df is None or getattr(df, "empty", True):
            return None
        return df
    except Exception as e:
        log.warning(f"  intraday_cache read {symbol} fail: {e}")
        return None
