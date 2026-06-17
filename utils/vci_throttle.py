"""
utils/vci_throttle.py — Global rate throttle + safe wrapper cho VCI calls (V2 pipeline)
========================================================================================
Mục đích: fix lỗi "429 Too Many Requests" của VCI trong pipeline v2 mà KHÔNG
động đến utils/helpers.py (shared với v3 — đổi safe_run ở đó sẽ throttle nhầm cả
KBS/CafeF và ảnh hưởng toàn bộ v3).

Nguyên nhân 429:
    nhiều thread × tenacity-retry NỘI BỘ của vnstock_data × retry THỦ CÔNG
    × nhiều endpoint/symbol × 2 step chạy nối nhau (snapshot → order_flow)
    → burst request vượt rate limit VCI.

Cơ chế:
  - throttle(): cổng min-interval TOÀN CỤC (trong 1 process) — đảm bảo 2 call
    VCI bất kỳ (mọi thread) cách nhau ≥ VCI_MIN_INTERVAL giây. Trần throughput
    = 1/interval req/s.
    Lưu ý: step_snapshot_v2 và step_order_flow_v2 chạy là 2 PROCESS riêng → mỗi
    process có throttle độc lập (đúng ý muốn). Khoảng cách giữa 2 step do COOLDOWN
    ở đầu step_order_flow_v2 xử lý.
  - vci_safe_run(): drop-in thay safe_run cho call VCI — có throttle + tùy chọn quiet.

Tinh chỉnh khi test (KHÔNG cần sửa code), set env trên workflow/dispatch:
    VCI_MIN_INTERVAL   (mặc định 0.20s = ~5 req/s).  Tăng nếu vẫn 429.
"""
import os
import logging
import threading
import time
import traceback

log = logging.getLogger(__name__)

# Min-interval giữa 2 call VCI bất kỳ trong cùng process (giây).
_VCI_MIN_INTERVAL = float(os.environ.get("VCI_MIN_INTERVAL", "0.20"))
_VCI_LOCK         = threading.Lock()
_VCI_LAST_CALL    = [0.0]   # list để mutable trong closure


def throttle() -> None:
    """Cổng min-interval toàn cục: serialize thời điểm FIRE của mọi call VCI."""
    if _VCI_MIN_INTERVAL <= 0:
        return
    with _VCI_LOCK:
        now  = time.monotonic()
        wait = _VCI_MIN_INTERVAL - (now - _VCI_LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _VCI_LAST_CALL[0] = time.monotonic()


def is_rate_limited(err) -> bool:
    """True nếu lỗi là 429 / Too Many Requests (để backoff dài hơn)."""
    s = str(err).lower()
    return "429" in s or "too many" in s


def vci_safe_run(label: str, fn, quiet: bool = False):
    """
    Drop-in thay safe_run cho call VCI: đi qua throttle TRƯỚC, rồi catch + log.

      quiet=True → lỗi chỉ log WARNING gọn, KHÔNG in traceback. Dùng cho call hay
                   fail lành tính (vd prop_trade khi mã không có giao dịch tự doanh:
                   vnstock_data tự gọi .str trên cột rỗng → AttributeError; đây là
                   LIB BUG, safe_run/None là hành vi đúng — chỉ cần khỏi spam log).

    Trả None khi lỗi (giữ nguyên hành vi của safe_run).
    """
    throttle()
    try:
        result = fn()
        log.info(f"  ✅ {label}")
        return result
    except Exception as e:
        if quiet:
            log.warning(f"  ⚠️ {label}: {type(e).__name__} — bỏ qua (không có data)")
        else:
            log.error(f"  ❌ {label}: {e}")
            traceback.print_exc()
        return None
