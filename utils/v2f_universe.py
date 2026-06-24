"""
utils/v2f_universe.py — Universe cho nhánh V2F (full VN100 + HNX30, monitor cả rổ)
==================================================================================
FORK của utils/universe_v2.py. KHÁC BIỆT DUY NHẤT:
  - V2  (universe_v2): VN100 → cắt top_x gainer + top_x loser (~40 mã).
  - V2F (file này)   : lấy ĐỦ rổ core (VN100 + HNX30 = ~130 mã), KHÔNG cắt.
    'group' chỉ là provenance theo dấu %change; scoring tự surface mã tăng/giảm.

Lý do tách file (không tham số hoá): yêu cầu giữ V2 hiện tại nguyên vẹn và
V2F là một flow độc lập hoàn toàn (file .py + output riêng, prefix v2f_).

ISOLATION:
  - Module RIÊNG của V2F, dùng chung utils/vci_throttle.py (throttle/circuit
    breaker) — KHÔNG fork lớp infra. V2F chạy ở runner/process riêng nên không
    chia sẻ state throttle với V2 (không sao — mỗi process tự bảo vệ quota).

OUTPUT ranking rows giữ ĐÚNG schema mà scoring đọc:
    symbol, price_change_percent_1d, price_change_1d, accumulated_value, group

MULTI-GROUP (2026-06-24):
  Universe = hợp các group trong V2F_INDEX_GROUPS, gom theo THỨ TỰ liệt kê,
  dedupe bằng `seen` set. Mặc định "VN100,HNX30".
  - VN100 = sàn HSX, HNX30 = sàn HNX → hai rổ RỜI NHAU (overlap=0, đã verify
    bằng diag_hnx30_coverage 2026-06-24: 0 trùng, universe gộp = 130 mã).
  - Movers (%change) lấy từ TopStock index=VNINDEX = chỉ HOSE → mã HNX KHÔNG
    có trong movers → pct=None → mặc định GAINER (đúng quy ước hiện hành;
    _attach_daily_change tự xử None). 'group' chỉ là provenance.
  - Fundamentals của HNX30 đã nằm sẵn trong finance cache (step_finance_scan
    _CORE_INDEX_GROUPS = ["VN100","HNX30"]) → không tốn thêm call KBS.

ENV overrides:
    V2F_INDEX_GROUPS = "VN100,HNX30"  # danh sách rổ core (phẩy ngăn cách)
    V2F_INDEX_GROUP  = "VN100"        # [deprecated] fallback nếu GROUPS rỗng
    V2F_RANK_LIMIT   = "300"          # limit kéo gainer/loser toàn TT (pass 1)
"""
import os
import logging

import pandas as pd
from vnstock_data import TopStock, Listing

from utils.vci_throttle import vci_safe_run

log = logging.getLogger(__name__)

# [deprecated single] giữ lại cho tương thích ngược (diag/caller cũ tham chiếu).
INDEX_GROUP = os.environ.get("V2F_INDEX_GROUP", "VN100")

# Danh sách rổ core — gom theo thứ tự, dedupe khi build.
INDEX_GROUPS = [
    g.strip().upper()
    for g in os.environ.get("V2F_INDEX_GROUPS", "VN100,HNX30").split(",")
    if g.strip()
] or [INDEX_GROUP]

RANK_LIMIT = int(os.environ.get("V2F_RANK_LIMIT", "300"))

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


def _build_core_universe(index_groups: list) -> list:
    """
    Gom thành viên nhiều group theo THỨ TỰ, dedupe bằng `seen`.
    Trả list[str] (đã upper, đã loại trùng). Log từng group + tổng.
    """
    seen: set = set()
    universe: list = []
    for grp in index_groups:
        members = fetch_index_members(grp)
        added = 0
        for s in members:
            if s and s not in seen:
                seen.add(s)
                universe.append(s)
                added += 1
        log.info(f"[v2f-universe] {grp}: {len(members)} mã → +{added} mới "
                 f"(tổng {len(universe)})")
    return universe


def _market_movers(limit: int):
    """Kéo gainer + loser toàn thị trường (VNINDEX) với limit lớn — pass 1."""
    ins = TopStock()
    gainers = vci_safe_run("gainer", lambda: ins.gainer(index="VNINDEX", limit=limit))
    losers  = vci_safe_run("loser",  lambda: ins.loser(index="VNINDEX",  limit=limit))
    return gainers, losers


def _movers_lookup(gainers, losers, universe: set) -> dict:
    """Gộp gainer+loser → map symbol → {schema cols} (chỉ giữ mã trong universe)."""
    out: dict = {}
    for df in (gainers, losers):
        if df is None or getattr(df, "empty", True) or "symbol" not in df.columns:
            continue
        d = df.copy()
        d["symbol"] = d["symbol"].astype(str).str.strip().str.upper()
        d = d[d["symbol"].isin(universe)]
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


def build_v2f_universe(index_groups=None,
                       rank_limit: int = RANK_LIMIT):
    """
    Trả về (symbol_jobs, ranking_rows) cho TOÀN BỘ rổ core (VN100 + HNX30, ~130 mã).
      symbol_jobs  : list[(symbol, group)] — universe pass 2 (đã dedupe)
      ranking_rows : list[dict]            — ghi v2f_ranking.json cho scoring

    index_groups: list[str] | str | None
      - None  → dùng INDEX_GROUPS (mặc định ["VN100","HNX30"]).
      - str   → 1 group đơn (tương thích ngược cách gọi cũ build_v2f_universe("VN100")).
      - list  → gom nhiều group theo thứ tự, dedupe.

    group = "LOSER" nếu %change < 0, còn lại (>=0 / =0 / thiếu) → "GAINER".
    Mã thiếu %change (mã HNX hoặc ngoài movers) giữ với pct=None;
    _attach_daily_change tự xử None.
    """
    if index_groups is None:
        index_groups = INDEX_GROUPS
    elif isinstance(index_groups, str):
        index_groups = [g.strip().upper() for g in index_groups.split(",") if g.strip()]

    universe_list = _build_core_universe(index_groups)
    universe = set(universe_list)
    log.info(f"[v2f-universe] core {'+'.join(index_groups)}: {len(universe)} mã (FULL)")
    if not universe:
        log.error(f"[v2f-universe] {index_groups} rỗng — không build được universe")
        return [], []

    gainers, losers = _market_movers(rank_limit)
    look = _movers_lookup(gainers, losers, universe)

    ranking_rows = []
    missing = 0
    for sym in sorted(universe):
        r = look.get(sym)
        if r is None:
            missing += 1
            r = {"symbol": sym, _PCT_COL: None, _ABS_COL: None, _VAL_COL: None}
        pct = r.get(_PCT_COL)
        r["group"] = "LOSER" if (pct is not None and pct < 0) else "GAINER"
        ranking_rows.append(r)

    n_gain = sum(1 for r in ranking_rows if r["group"] == "GAINER")
    n_lose = sum(1 for r in ranking_rows if r["group"] == "LOSER")
    log.info(f"[v2f-universe] {len(universe)} mã → {n_gain} gainer / {n_lose} loser "
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
