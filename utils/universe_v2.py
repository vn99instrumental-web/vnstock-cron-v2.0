"""
utils/universe_v2.py — VN100 universe + recomputed gainer/loser (V2 only)
==========================================================================
Đổi nguồn universe của step_snapshot_v2.py:
  CŨ : top 10 gainer + 10 loser TOÀN thị trường (TopStock VNINDEX).
  MỚI: VN100 → tính lại gainer/loser TRONG rổ → top X mỗi phía theo %.

Hai pass (giữ throttle nhẹ):
  Pass 1 (ở đây, nhẹ): lấy VN100 list + %thay-đổi toàn thị trường (TopStock,
                       1–2 call) → lọc isin(VN100) → top X gainer + X loser.
  Pass 2 (ở snapshot): TA 12M + intraday + depth + FF chỉ chạy trên ~2X mã.

ISOLATION:
  - Module RIÊNG của V2, KHÔNG đụng utils/helpers.py (shared với v3).
  - Mọi call VCI đi qua vci_safe_run (circuit breaker / kill switch / throttle)
    đồng nhất với phần còn lại của pipeline V2.

OUTPUT ranking rows giữ ĐÚNG schema mà step_scoring_v2._attach_daily_change đọc:
    symbol, price_change_percent_1d, price_change_1d, accumulated_value, group
  → scoring tự map sang chg_pct_1d / chg_abs_vnd / accumulated_value, KHÔNG sửa
    logic _attach_daily_change.

ENV overrides (đổi không cần sửa code):
    VN100_INDEX_GROUP = "VN100"   # rổ universe
    VN100_RANK_LIMIT  = "300"     # limit kéo gainer/loser toàn thị trường (pass 1)
    VN100_TOP_X       = "20"      # số mã mỗi phía gainer / loser
"""
import os
import logging

import pandas as pd
from vnstock_data import TopStock, Listing

# Throttle riêng V2 (fix 429) — KHÔNG đụng helpers.py
from utils.vci_throttle import vci_safe_run

log = logging.getLogger(__name__)

INDEX_GROUP = os.environ.get("VN100_INDEX_GROUP", "VN100")
RANK_LIMIT  = int(os.environ.get("VN100_RANK_LIMIT", "300"))
TOP_X       = int(os.environ.get("VN100_TOP_X", "20"))

# Cột TopStock gainer/loser mà _attach_daily_change cần (xác nhận từ schema
# ranking.json hiện hành: price_change_percent_1d / price_change_1d /
# accumulated_value).
_PCT_COL = "price_change_percent_1d"
_ABS_COL = "price_change_1d"
_VAL_COL = "accumulated_value"
_RANK_COLS = ["symbol", _PCT_COL, _ABS_COL, _VAL_COL]


def fetch_index_members(group: str = INDEX_GROUP) -> list:
    """
    Thành viên 1 index qua Listing.symbols_by_group. Trả [] nếu fail.
    symbols_by_group trả pandas Series (đôi khi DataFrame/list tuỳ phiên bản).
    Pattern lấy từ step_finance_scan._fetch_index_members, tách ra để V2 dùng chung.
    """
    res = vci_safe_run(
        f"symbols_by_group({group})",
        lambda: Listing(source="VCI").symbols_by_group(group=group),
    )
    if res is None:
        return []
    try:
        if isinstance(res, pd.Series):
            syms = res.dropna().astype(str).tolist()
        elif isinstance(res, pd.DataFrame):
            if res.empty:
                return []
            col = "symbol" if "symbol" in res.columns else res.columns[0]
            syms = res[col].dropna().astype(str).tolist()
        elif isinstance(res, (list, tuple)):
            syms = [str(s) for s in res]
        else:
            return []
    except Exception as e:
        log.warning(f"  [universe] parse {group} members lỗi: {e}")
        return []
    return [s.strip().upper() for s in syms if s and s.strip()]


def _market_movers(limit: int):
    """Kéo gainer + loser toàn thị trường (VNINDEX) với limit lớn — pass 1."""
    ins = TopStock()
    gainers = vci_safe_run(
        "gainer", lambda: ins.gainer(index="VNINDEX", limit=limit))
    losers = vci_safe_run(
        "loser", lambda: ins.loser(index="VNINDEX", limit=limit))
    return gainers, losers


def _select(df, vn100: set, top_x: int, group: str, ascending: bool) -> list:
    """Lọc df về VN100, sort theo %thay-đổi, giữ đúng cột schema, lấy top_x."""
    if df is None or getattr(df, "empty", True) or "symbol" not in df.columns:
        return []
    d = df.copy()
    d["symbol"] = d["symbol"].astype(str).str.strip().str.upper()
    d = d[d["symbol"].isin(vn100)]
    if d.empty:
        return []

    # Đảm bảo đủ cột (mã thiếu cột → None; _attach_daily_change tự xử None)
    for c in _RANK_COLS:
        if c not in d.columns:
            d[c] = None

    # Sort tường minh theo % để không phụ thuộc thứ tự gốc của TopStock sau khi lọc
    d[_PCT_COL] = pd.to_numeric(d[_PCT_COL], errors="coerce")
    d = d.sort_values(_PCT_COL, ascending=ascending, na_position="last")

    rows = d[_RANK_COLS].head(top_x).to_dict(orient="records")
    for r in rows:
        r["group"] = group
    return rows


def build_vn100_universe(top_x: int = TOP_X,
                         index_group: str = INDEX_GROUP,
                         rank_limit: int = RANK_LIMIT):
    """
    Trả về (symbol_jobs, ranking_rows):
      symbol_jobs  : list[(symbol, group)] — universe pass 2 (≤ 2*top_x, đã dedupe)
      ranking_rows : list[dict]            — ghi ranking_v2.json cho scoring đọc

    group = "GAINER" / "LOSER" tính lại theo dấu %thay-đổi trong rổ VN100.
    """
    vn100 = set(fetch_index_members(index_group))
    log.info(f"[universe] {index_group}: {len(vn100)} mã")
    if not vn100:
        log.error(f"[universe] {index_group} rỗng — không build được universe")
        return [], []

    gainers, losers = _market_movers(rank_limit)
    g_rows = _select(gainers, vn100, top_x, "GAINER", ascending=False)
    l_rows = _select(losers,  vn100, top_x, "LOSER",  ascending=True)

    log.info(
        f"[universe] limit={rank_limit} → bắt được "
        f"{len(g_rows)}/{top_x} gainer + {len(l_rows)}/{top_x} loser "
        f"trong {index_group}"
    )
    if len(g_rows) < top_x or len(l_rows) < top_x:
        log.warning(
            f"[universe] chưa đủ top_x — tăng VN100_RANK_LIMIT (hiện {rank_limit}) "
            f"hoặc do phiên ít mã VN100 biến động. Nếu tăng limit vẫn không đủ "
            f"→ TopStock đang cap số dòng trả về."
        )

    ranking_rows = g_rows + l_rows

    # Dedupe symbol_jobs (an toàn dù gainer/loser về lý thuyết không trùng)
    seen: set = set()
    symbol_jobs = []
    for r in ranking_rows:
        sym = r.get("symbol")
        if sym and sym not in seen:
            seen.add(sym)
            symbol_jobs.append((sym, r["group"]))

    log.info(f"[universe] pass-2 universe: {len(symbol_jobs)} mã")
    return symbol_jobs, ranking_rows
