"""
utils/vci_throttle.py — Global rate throttle + circuit breaker cho VCI calls (V2 pipeline)
==========================================================================================
Mục đích: fix lỗi "429 Too Many Requests" của VCI trong pipeline v2 mà KHÔNG
động đến utils/helpers.py (shared với v3).

Nguyên nhân 429 (xác nhận từ log 2026-06-18):
    - step_snapshot_v2: endpoint NHẸ (history/ratio) — workers=5 + interval 0.2s
      → chỉ 1/20 fail. Chấp nhận được.
    - step_order_flow_v2: intraday(page_size=10000) là endpoint NẶNG — giãn thời
      điểm BẮT ĐẦU 0.2s không đủ, vì nhiều call nặng OVERLAP in-flight nhiều giây
      → VCI bão hòa → mọi request đang bay đều 429. Per-call backoff vô dụng vì
      các worker khác vẫn hammer trong lúc 1 mã đang nghỉ.

Cơ chế (2 lớp):
  1) throttle() — cổng min-interval TOÀN CỤC: 2 call VCI bất kỳ cách nhau
     >= min-interval giây (giãn thời điểm fire).
  2) CIRCUIT BREAKER — khi BẤT KỲ thread nào dính 429, note_rate_limited() đặt
     "phạt toàn cục": MỌI thread (qua throttle) nghỉ chung tới khi hết phạt. Đây
     là collective backoff — để cửa sổ rate của VCI kịp hồi, thay vì từng call tự
     lùi rời rạc. vci_safe_run tự gọi note_rate_limited() khi bắt được lỗi 429.

Áp dụng: snapshot dùng mặc định; order_flow tự set_min_interval() cao hơn + workers
thấp hơn vì endpoint nặng. Hai step là 2 PROCESS riêng -> throttle độc lập; khoảng
cách giữa 2 step do COOLDOWN ở đầu order_flow xử lý.

Tinh chỉnh khi test (KHÔNG cần sửa code), set env trên workflow/dispatch:
    VCI_MIN_INTERVAL   (mặc định 0.20s = ~5 req/s) — giãn cách mặc định
    VCI_PENALTY        (mặc định 5.0s)             — thời gian phạt chung sau mỗi 429
"""
import os
import logging
import threading
import time
import traceback

log = logging.getLogger(__name__)

# Min-interval giữa 2 call VCI bất kỳ trong cùng process (giây).
_VCI_MIN_INTERVAL = float(os.environ.get("VCI_MIN_INTERVAL", "0.20"))
# Phạt toàn cục mỗi lần dính 429 (giây) — circuit breaker.
# 2026-06-18 (lần 3): 5 → 8s. Lib retry nội bộ làm 1 lần 429 có thể là 3-5 HTTP
# request hammer trong vài giây — penalty ngắn hơn không đủ cho rate window hồi.
_VCI_PENALTY      = float(os.environ.get("VCI_PENALTY", "8.0"))
# Trần phạt: dù 429 dồn dập, không hoãn quá ngần này kể từ hiện tại (giây).
_VCI_PENALTY_CAP  = 30.0

_VCI_LOCK          = threading.Lock()
_VCI_LAST_CALL     = [0.0]   # monotonic time của call gần nhất
_VCI_PENALTY_UNTIL = [0.0]   # monotonic time đến khi hết phạt toàn cục
_VCI_BLOCKED       = [None]  # set khi VCI server-side block (vd "chuẩn bị phiên")
                             # → mọi call sau bail tức thì, không gọi API.

# Pattern phát hiện server-side blackout: VCI trả ValueError với thông điệp tiếng
# Việt trong cửa sổ ~07:00-09:00 ICT trước giờ mở phiên ("data_status=preparing").
# Lib vnstock_data không nhận diện được → retry nội bộ 3-5 lần × 20 mã × 3 attempt
# ngoài → đốt 600s+. Kill switch dưới đây phát hiện lần đầu rồi bail mọi call tiếp.
_BLOCK_PATTERNS = (
    "chuẩn bị phiên",
    "dữ liệu khớp lệnh không thể truy cập",
    "data_status=preparing",
    "is_trading_hour=false",
)


def set_min_interval(seconds: float) -> None:
    """Cho phép từng step override min-interval lúc runtime (vd order_flow nặng hơn)."""
    global _VCI_MIN_INTERVAL
    _VCI_MIN_INTERVAL = max(0.0, float(seconds))
    log.info(f"  [throttle] min-interval = {_VCI_MIN_INTERVAL:.2f}s, penalty = {_VCI_PENALTY:.1f}s")


def is_rate_limited(err) -> bool:
    """True nếu lỗi là 429 / Too Many Requests."""
    s = str(err).lower()
    return "429" in s or "too many" in s


def is_premarket_block(err) -> bool:
    """True nếu VCI từ chối phục vụ vì đang chuẩn bị phiên mới (~07:00-09:00 ICT)."""
    s = str(err).lower()
    return any(p in s for p in _BLOCK_PATTERNS)


def is_blocked() -> str | None:
    """Trả về lý do nếu VCI đang bị block toàn cục (kill switch đã bật)."""
    return _VCI_BLOCKED[0]


def note_premarket_block(reason: str) -> None:
    """Bật kill switch toàn cục: mọi call vci_safe_run sau sẽ bail tức thì."""
    with _VCI_LOCK:
        if _VCI_BLOCKED[0] is None:
            _VCI_BLOCKED[0] = reason[:120]
            log.warning(f"  🚫 KILL SWITCH: VCI blocked — {_VCI_BLOCKED[0]}")
            log.warning(f"  🚫 Mọi call VCI tiếp theo sẽ bail tức thì để tránh đốt thời gian.")


def reset_kill_switch() -> None:
    """Reset kill switch (chỉ dùng trong test/manual recovery)."""
    with _VCI_LOCK:
        _VCI_BLOCKED[0] = None


def note_rate_limited() -> None:
    """
    Gọi khi gặp 429 -> bật circuit breaker: đẩy mốc hết-phạt ra thêm _VCI_PENALTY
    giây (có trần). Mọi thread qua throttle() sau đó sẽ nghỉ chung tới mốc này.
    """
    with _VCI_LOCK:
        now    = time.monotonic()
        target = max(_VCI_PENALTY_UNTIL[0], now + _VCI_PENALTY)
        _VCI_PENALTY_UNTIL[0] = min(now + _VCI_PENALTY_CAP, target)


def throttle() -> None:
    """
    Cổng toàn cục: (1) chờ hết phạt 429 nếu đang bị (circuit breaker), rồi
    (2) đảm bảo cách call trước >= min-interval. Serialize qua _VCI_LOCK nên mỗi
    thread chỉ ngủ phần thời gian CÒN LẠI -> tổng trễ ~= phạt + N x min_interval.
    """
    with _VCI_LOCK:
        now = time.monotonic()
        # (1) circuit breaker: chờ hết phạt chung
        if now < _VCI_PENALTY_UNTIL[0]:
            time.sleep(_VCI_PENALTY_UNTIL[0] - now)
            now = time.monotonic()
        # (2) min-interval gate
        if _VCI_MIN_INTERVAL > 0:
            wait = _VCI_MIN_INTERVAL - (now - _VCI_LAST_CALL[0])
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
        _VCI_LAST_CALL[0] = now


def vci_safe_run(label: str, fn, quiet: bool = False):
    """
    Drop-in thay safe_run cho call VCI: đi qua throttle TRƯỚC, rồi catch + log.

      quiet=True -> lỗi chỉ log WARNING gọn, KHÔNG in traceback. Dùng cho call hay
                   fail lành tính (vd prop_trade khi mã không có giao dịch tự doanh:
                   vnstock_data tự gọi .str trên cột rỗng -> AttributeError; đây là
                   LIB BUG, safe_run/None là hành vi đúng — chỉ cần khỏi spam log).

    Khi lỗi là 429 -> bật circuit breaker toàn cục (note_rate_limited) để mọi thread
    cùng lùi.
    Khi lỗi là blackout server-side ("chuẩn bị phiên") -> bật kill switch (note_premarket_block),
    mọi call sau bail tức thì (không qua throttle, không gọi API).
    Trả None khi lỗi (giữ nguyên hành vi của safe_run).
    """
    # Kill switch: bail tức thì không gọi API → không tốn API quota, không tốn thời gian.
    if _VCI_BLOCKED[0] is not None:
        if not quiet:
            log.warning(f"  ⏭️  {label}: skipped (VCI blocked: {_VCI_BLOCKED[0]})")
        return None

    throttle()
    try:
        result = fn()
        log.info(f"  ✅ {label}")
        return result
    except Exception as e:
        if is_premarket_block(e):
            note_premarket_block(str(e).split("\n")[0])
        elif is_rate_limited(e):
            note_rate_limited()
        if quiet:
            log.warning(f"  ⚠️ {label}: {type(e).__name__} — bỏ qua (không có data)")
        else:
            log.error(f"  ❌ {label}: {e}")
            traceback.print_exc()
        return None
