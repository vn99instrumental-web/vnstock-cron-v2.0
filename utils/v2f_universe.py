"""
utils/v2f_universe.py — Universe cho nhánh V2F (full VN100, monitor cả rổ)
==================================================================================
FORK của utils/universe_v2.py. KHÁC BIỆT DUY NHẤT:
  - V2  (universe_v2): VN100 → cắt top_x gainer + top_x loser (~40 mã).
  - V2F (file này)   : lấy ĐỦ rổ VN100 = 100 mã, KHÔNG cắt.
    'group' chỉ là provenance theo dấu %change; scoring tự surface mã tăng/giảm.

Lý do tách file (không tham số hoá): yêu cầu giữ V2 hiện tại nguyên vẹn và
V2F là một flow độc lập hoàn toàn (file .py + output riêng, prefix v2f_).

ISOLATION:
  - Module RIÊNG của V2F, dùng chung utils/vci_throttle.py (throttle/circuit
    breaker) — KHÔNG fork lớp infra. V2F chạy ở runner/process riêng nên không
    chia sẻ state throttle với V2 (không sao — mỗi process tự bảo vệ quota).

OUTPUT ranking rows giữ ĐÚNG schema mà scoring đọc:
    symbol, price_change_percent_1d, price_change_1d, accumulated_value, group

CURRENT SCOPE (2026-10-09):
  Universe chỉ gồm đúng 100 thành viên VN100. Không dùng HNX30 và không dùng toàn bộ HSX.
  Nếu API group cũ rỗng: thử Reference.index.members("VN100"), sau đó dùng snapshot
  VN100 gần nhất đã commit; mọi nguồn đều phải qua chốt đúng 100 mã.
ENV overrides:
    V2F_INDEX_GROUPS = "VN100"        # chỉ lấy đúng rổ VN100
    V2F_INDEX_GROUP  = "VN100"        # [deprecated] fallback nếu GROUPS rỗng
    V2F_RANK_LIMIT   = "300"          # limit kéo gainer/loser toàn TT (pass 1)
"""
import os
import logging
import json
from pathlib import Path

import pandas as pd
from vnstock_data import TopStock, Listing, Reference

from utils.vci_throttle import vci_safe_run

log = logging.getLogger(__name__)

# [deprecated single] giữ lại cho tương thích ngược (diag/caller cũ tham chiếu).
INDEX_GROUP = os.environ.get("V2F_INDEX_GROUP", "VN100")

# Danh sách rổ core — gom theo thứ tự, dedupe khi build.
INDEX_GROUPS = [
    g.strip().upper()
    for g in os.environ.get("V2F_INDEX_GROUPS", "VN100").split(",")   # 2026-08-26: BO HNX30 -> chi VN100/HOSE (breadth khop VNINDEX, het lech pham vi)
    if g.strip()
] or [INDEX_GROUP]

RANK_LIMIT = int(os.environ.get("V2F_RANK_LIMIT", "300"))

_PCT_COL = "price_change_percent_1d"
_ABS_COL = "price_change_1d"
_VAL_COL = "accumulated_value"
_RANK_COLS = ["symbol", _PCT_COL, _ABS_COL, _VAL_COL]
_LAST_GOOD_RANKING = Path(__file__).resolve().parent.parent / "output" / "v2f_ranking.json"


def _parse_symbols(res) -> list:
    """Chuẩn hoá symbol từ các dạng trả về của vnstock Listing."""
    if res is None:
        return []
    try:
        if isinstance(res, pd.Series):
            syms = res.dropna().astype(str).tolist()
        elif isinstance(res, pd.DataFrame):
            if res.empty:
                return []
            col = next((c for c in res.columns
                        if str(c).strip().lower() in ("symbol", "ticker", "code")),
                       res.columns[0])
            syms = res[col].dropna().astype(str).tolist()
        elif isinstance(res, (list, tuple)):
            syms = [str(s) for s in res]
        else:
            return []
    except Exception as e:
        log.warning(f"  [v2f-universe] parse symbols lỗi: {e}")
        return []
    return list(dict.fromkeys(s.strip().upper() for s in syms if s and s.strip()))


def _valid_index_members(group: str, members: list) -> bool:
    """VN100 phải đủ đúng 100 mã; group khác chỉ cần không rỗng."""
    if group.upper() == "VN100" and len(members) != 100:
        log.error("[v2f-universe] từ chối %s: cần đúng 100 mã, nhận %d", group, len(members))
        return False
    return bool(members)


def fetch_index_members(group: str = INDEX_GROUP) -> list:
    """Lấy đúng thành viên index; không bao giờ mở rộng sang toàn sàn."""
    res = vci_safe_run(
        f"symbols_by_group({group})",
        lambda: Listing(source="VCI").symbols_by_group(group=group),
    )
    members = _parse_symbols(res)
    if _valid_index_members(group, members):
        return members

    # API Reference mới tách rõ thành phần chỉ số khỏi danh sách toàn sàn.
    try:
        ref = Reference()
        index_api = getattr(ref, "index", None)
        members_fn = getattr(index_api, "members", None)
        if callable(members_fn):
            fallback = vci_safe_run(
                f"Reference.index.members({group})",
                lambda: members_fn(group),
            )
            members = _parse_symbols(fallback)
            if _valid_index_members(group, members):
                log.info("[v2f-universe] Reference index fallback %s: %d mã", group, len(members))
                return members
    except Exception as e:
        log.warning("[v2f-universe] Reference index fallback không khả dụng: %s", e)

    # Cuối cùng dùng snapshot index gần nhất đã commit. Chỉ nhận đúng 100 mã để
    # tránh vô tình dùng file từng được tạo từ toàn bộ HSX.
    if group.upper() == "VN100":
        try:
            rows = json.loads(_LAST_GOOD_RANKING.read_text(encoding="utf-8"))
            cached = _parse_symbols(pd.DataFrame(rows))
            if len(cached) == 100:
                log.warning("[v2f-universe] dùng snapshot VN100 gần nhất: 100 mã")
                return cached
            log.error("[v2f-universe] từ chối snapshot: cần 100 mã, nhận %d", len(cached))
        except Exception as e:
            log.error("[v2f-universe] không đọc được snapshot VN100: %s", e)
    return members

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
    Trả về (symbol_jobs, ranking_rows) cho TOÀN BỘ rổ VN100 (100 mã).
      symbol_jobs  : list[(symbol, group)] — universe pass 2 (đã dedupe)
      ranking_rows : list[dict]            — ghi v2f_ranking.json cho scoring

    index_groups: list[str] | str | None
      - None  → dùng INDEX_GROUPS (mặc định ["VN100"]).
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
