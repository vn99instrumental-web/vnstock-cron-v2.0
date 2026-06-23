"""
utils/v2f_universe.py — Universe cho nhánh V2F (full-VN100, monitor cả rổ)
==========================================================================
FORK của utils/universe_v2.py. KHÁC BIỆT DUY NHẤT:
  - V2  (universe_v2): VN100 → cắt top_x gainer + top_x loser (~40 mã).
  - V2F (file này)   : lấy ĐỦ 100 mã VN100, KHÔNG cắt. 'group' chỉ là
    provenance theo dấu %change; scoring tự surface mã tăng/giảm mạnh.

Lý do tách file (không tham số hoá): yêu cầu giữ V2 hiện tại nguyên vẹn và
V2F là một flow độc lập hoàn toàn (file .py + output riêng, prefix v2f_).

ISOLATION:
  - Module RIÊNG của V2F, dùng chung utils/vci_throttle.py (throttle/circuit
    breaker) — KHÔNG fork lớp infra. V2F chạy ở runner/process riêng nên không
    chia sẻ state throttle với V2 (không sao — mỗi process tự bảo vệ quota).

OUTPUT ranking rows giữ ĐÚNG schema mà scoring đọc:
    symbol, price_change_percent_1d, price_change_1d, accumulated_value, group

ENV overrides:
    V2F_INDEX_GROUP = "VN100"   # rổ universe
    V2F_RANK_LIMIT  = "300"     # limit kéo gainer/loser toàn thị trường (pass 1)
"""
import os
import logging

import pandas as pd
from vnstock_data import TopStock, Listing

from utils.vci_throttle import vci_safe_run

log = logging.getLogger(__name__)

INDEX_GROUP = os.environ.get("V2F_INDEX_GROUP", "VN100")
RANK_LIMIT  = int(os.environ.get("V2F_RANK_LIMIT", "300"))

_PCT_COL = "price_change_percent_1d"
_ABS_COL = "price_change_1d"
_VAL_COL = "accumulated_value"
_RANK_COLS = ["symbol", _PCT_COL, _ABS_COL, _VAL_COL]


def fetch_index_members(group: str = INDEX_GROUP) -> list:
    """Thành viên 1 index qua Listing.symbols_by_group. Trả [] nếu fail."""
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
        log.warning(f"  [v2f-universe] parse {group} members lỗi: {e}")
        return []
    return [s.strip().upper() for s in syms if s and s.strip()]


def _market_movers(limit: int):
    """Kéo gainer + loser toàn thị trường (VNINDEX) với limit lớn — pass 1."""
    ins = TopStock()
    gainers = vci_safe_run("gainer", lambda: ins.gainer(index="VNINDEX", limit=limit))
    losers  = vci_safe_run("loser",  lambda: ins.loser(index="VNINDEX",  limit=limit))
    return gainers, losers


def _movers_lookup(gainers, losers, vn100: set) -> dict:
    """Gộp gainer+loser → map symbol → {schema cols} (chỉ giữ mã VN100)."""
    out: dict = {}
    for df in (gainers, losers):
        if df is None or getattr(df, "empty", True) or "symbol" not in df.columns:
            continue
        d = df.copy()
        d["symbol"] = d["symbol"].astype(str).str.strip().str.upper()
        d = d[d["symbol"].isin(vn100)]
        if d.empty:
            continue
        for c in _RANK_COLS:
            if c not in d.columns:
                d[c] = None
        d[_PCT_COL] = pd.to_numeric(d[_PCT_COL], errors="coerce")
        for r in d[_RANK_COLS].to_dict(orient="records"):
            sym = r["symbol"]
            if sym not in out or out[sym].get(_PCT_COL) is None:
                out[sym] = r
    return out


def build_v2f_universe(index_group: str = INDEX_GROUP,
                       rank_limit: int = RANK_LIMIT):
    """
    Trả về (symbol_jobs, ranking_rows) cho TOÀN BỘ rổ VN100 (~100 mã).
      symbol_jobs  : list[(symbol, group)] — universe pass 2 (đã dedupe)
      ranking_rows : list[dict]            — ghi v2f_ranking.json cho scoring

    group = "LOSER" nếu %change < 0, còn lại (>=0 / =0 / thiếu) → "GAINER".
    Mã thiếu %change (ngoài top-limit / movers fail) vẫn giữ với pct=None;
    _attach_daily_change tự xử None.
    """
    vn100 = set(fetch_index_members(index_group))
    log.info(f"[v2f-universe] {index_group}: {len(vn100)} mã (FULL)")
    if not vn100:
        log.error(f"[v2f-universe] {index_group} rỗng — không build được universe")
        return [], []

    gainers, losers = _market_movers(rank_limit)
    look = _movers_lookup(gainers, losers, vn100)

    ranking_rows = []
    missing = 0
    for sym in sorted(vn100):
        r = look.get(sym)
        if r is None:
            missing += 1
            r = {"symbol": sym, _PCT_COL: None, _ABS_COL: None, _VAL_COL: None}
        pct = r.get(_PCT_COL)
        r["group"] = "LOSER" if (pct is not None and pct < 0) else "GAINER"
        ranking_rows.append(r)

    n_gain = sum(1 for r in ranking_rows if r["group"] == "GAINER")
    n_lose = sum(1 for r in ranking_rows if r["group"] == "LOSER")
    log.info(f"[v2f-universe] {len(vn100)} mã → {n_gain} gainer / {n_lose} loser "
             f"({missing} mã thiếu %change → mặc định GAINER)")

    seen: set = set()
    symbol_jobs = []
    for r in ranking_rows:
        sym = r.get("symbol")
        if sym and sym not in seen:
            seen.add(sym)
            symbol_jobs.append((sym, r["group"]))

    log.info(f"[v2f-universe] pass-2 universe: {len(symbol_jobs)} mã")
    return symbol_jobs, ranking_rows
