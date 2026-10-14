#!/usr/bin/env python3
"""
sync_supabase.py — [E1] Mirror ledger JSONL → Supabase (idempotent upsert).

Đọc sổ cái append-only:
  output/history/v2f_predictions_v4/YYYY-MM.jsonl  → v4_runs + v4_signals
  output/history/v2f_outcomes_v4/YYYY-MM.jsonl     → v4_outcomes (WIDE, ADR-002)

Nguyên tắc (CLAUDE.md):
  • Supabase là BẢN MIRROR; nguồn chân lý con số là Python pipeline + ledger.
  • Version-agnostic: đọc scoring_version/gate_version ĐỘNG từ từng dòng, KHÔNG hardcode.
  • Ghi CHỈ bằng service_role (bypass RLS). Secret chỉ ở env server — KHÔNG log ra.
  • Idempotent: upsert theo unique key (on_conflict) → chạy lại không nhân đôi.

Env bắt buộc (server-only):
  SUPABASE_URL  (hoặc NEXT_PUBLIC_SUPABASE_URL)
  SUPABASE_SERVICE_ROLE_KEY

Cách chạy:
  python3 scripts/sync_supabase.py                 # auto: các tháng có trong ledger
  python3 scripts/sync_supabase.py --months 2026-09
  python3 scripts/sync_supabase.py --dry-run       # chỉ transform + đếm, KHÔNG gọi network
  python3 scripts/sync_supabase.py --only outcomes # chỉ 1 nguồn (predictions|outcomes)

run_id: "<signal_date>_<snap_time>_<scoring_version>"; one run per version.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import requests
except ModuleNotFoundError:  # Dry-run/transform checks can run in a minimal Python runtime.
    requests = None

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
REVIEW_CONFIG = json.loads((ROOT / "config" / "scoring" / "review_versions.json").read_text(encoding="utf-8"))
REVIEW_VERSIONS = frozenset(REVIEW_CONFIG["versions"])
PRED_DIRS = (
    ROOT / "output" / "history" / "v2f_predictions_v4",
    ROOT / "output" / "history" / "v2f_predictions",
)
OUTC_DIRS = (
    ROOT / "output" / "history" / "v2f_outcomes_v4",
    ROOT / "output" / "history" / "v2f_outcomes",
)

ICT_OFFSET = "+07:00"                      # giờ VN
BUY_DECISIONS = {"BUY", "STRONG BUY"}      # đếm n_buy
BATCH = 200                                # số row/1 request PostgREST (nhỏ để tránh 504 khi breakdown jsonb lớn)
MAX_RETRY = 5                              # retry cho lỗi tạm (5xx / timeout / mạng)
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

# Supabase là serving layer, không phải bản sao lossless của ledger. Giữ các field
# mà dashboard/drill-down thực sự đọc; bản gốc đầy đủ vẫn nằm trong Git JSONL và
# được các job IC đọc trực tiếp. JSONB lặp tên khóa trên mỗi signal nên việc đưa
# toàn bộ prediction vào đây làm bảng v4_signals lớn hơn dữ liệu CSV rất nhiều.
SIGNAL_BREAKDOWN_KEYS = frozenset({
    # Join / nhãn / phân nhóm
    "pred_id", "industry", "sector_group", "confidence", "snap_time",
    "size_band", "exchange", "gates",
    # Giá, mức giao dịch và dữ liệu thô dùng để diễn giải
    "price", "entry", "stop", "stop_loss", "tp1", "tp2", "adtv_bil",
    "willr_14", "bb_position", "price_vs_ema200_pct", "ema200",
    "return_20d", "vnindex_return_20d", "low_52w", "high_52w",
    "vol_ma_ratio", "ff_intra_net", "ff_intra_ratio", "of_bp_pts",
    "n_supergroups_aligned", "ff_score", "fundamental_score",
    # Factor chi tiết
    "s_willr_mr", "s_bb_mr", "s_overext_ema", "s_rs_reversal", "s_deep_dd",
    "s_dist_52w", "s_vol_ratio_h", "s_ff_net", "s_of_phasefix", "s_prop_5d",
    "s_insider", "s_fund_core", "s_growth_core", "s_mkt_context", "s_trend_st",
    "s_depth_wall", "s_cf_core",
    # 6 nhóm, rank và shadow dùng trong trang chi tiết
    "trade_mean_reversion_norm", "trade_breakout_norm", "trade_flow_norm",
    "trade_fundamental_norm", "trade_growth_norm", "trade_context_norm",
    "rank_fund_grp", "rank_fund_uni", "rank_trend_grp", "rank_ff_grp",
    "rank_cf_grp", "rank_growth_grp",
    "score_trade_nomr", "decision_nomr", "_nomr_delta",
    "score_trade_altfund", "decision_altfund", "_altfund_delta",
    "score_trade_rank", "decision_rank", "_rank_delta",
    "score_trade_gate1", "decision_gate1", "_gate1_delta",
    # Mapping factor của scoring legacy v2.3
    "total_score", "norm_momentum", "norm_trend", "norm_ff",
    "norm_fundamental", "growth_score", "context_score",
})

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_supabase")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _num(v):
    """Ép về số nếu được, giữ None; tránh crash khi ledger có chuỗi lạ."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _snap_ts(signal_date: str, snap_time: str) -> str | None:
    """'2026-09-03' + '09:27' → '2026-09-03T09:27:00+07:00' (timestamptz cho v4_signals)."""
    if not signal_date or not snap_time:
        return None
    t = snap_time if snap_time.count(":") == 2 else f"{snap_time}:00"
    return f"{signal_date}T{t}{ICT_OFFSET}"


def _run_id(signal_date: str, snap_time: str, scoring_version: str | None) -> str:
    return f"{signal_date}_{snap_time}_{scoring_version or 'unknown'}"


def _months_available() -> list[str]:
    months = set()
    for d in (*PRED_DIRS, *OUTC_DIRS):
        if d.exists():
            for f in d.glob("*.jsonl"):
                if MONTH_RE.match(f.stem):
                    months.add(f.stem)
    return sorted(months)


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("bỏ dòng hỏng JSON %s:%d", path.name, i)


# ── Transform ────────────────────────────────────────────────────────────────
def build_signal_row(p: dict) -> dict:
    """1 prediction ledger → 1 row v4_signals với serving payload gọn."""
    sd, st = p.get("signal_date"), p.get("snap_time")
    breakdown = {
        key: value for key, value in p.items()
        if value is not None and (
            key in SIGNAL_BREAKDOWN_KEYS
            or (isinstance(value, (int, float)) and not isinstance(value, bool))
        )
    }
    return {
        "run_id":              _run_id(sd, st, p.get("scoring_version")),
        "signal_date":         sd,
        "snap_time":           _snap_ts(sd, st),
        "symbol":              p.get("symbol"),
        "regime":              p.get("regime"),
        "decision":            p.get("decision"),
        "score_trade":         _num(p.get("score_trade", p.get("total_score"))),
        "pre_total":           None,                        # không có trong ledger v4
        "extras":              None,                        # không có trong ledger v4
        "w_reg":               None,                        # không có trong ledger v4
        "breakdown":           breakdown,                   # lossless source vẫn là Git ledger
        "decision_nomr":       p.get("decision_nomr"),
        "score_trade_nomr":    _num(p.get("score_trade_nomr")),
        "mr_delta":            _num(p.get("_nomr_delta")),
        "decision_altfund":    p.get("decision_altfund"),
        "score_trade_altfund": _num(p.get("score_trade_altfund")),
        "extras_guard_flag":   None,                        # không có trong ledger v4
        "entry":               _num(p.get("entry")),
        "stop":                _num(p.get("stop", p.get("stop_loss"))),
        "tp1":                 _num(p.get("tp1")),
        "scoring_version":     p.get("scoring_version"),
        "gate_version":        None if p.get("gate_version") is None else str(p.get("gate_version")),
    }


def build_run_rows(preds: list[dict]) -> list[dict]:
    """Group predictions theo (signal_date, snap_time) → v4_runs (ADR-006)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in preds:
        groups[(p.get("signal_date"), p.get("snap_time"), p.get("scoring_version"))].append(p)

    rows = []
    for (sd, st, version), items in groups.items():
        first = items[0]
        dec_count = defaultdict(int)
        for it in items:
            dec_count[it.get("decision")] += 1
        n_buy = sum(v for k, v in dec_count.items() if k in BUY_DECISIONS)
        rows.append({
            "run_id":          _run_id(sd, st, version),
            "kind":            "intraday",                  # mọi run v4 là snap intraday (evidence)
            "started_at":      _snap_ts(sd, st),
            "scoring_version": version,
            "gate_version":    None if first.get("gate_version") is None else str(first.get("gate_version")),
            "universe_size":   len(items),
            "n_buy":           n_buy,
            "health": {
                "regime":            first.get("regime"),
                "universe_variant":  first.get("universe_variant"),
                "flow":              first.get("flow"),
                "registry_version":  first.get("registry_version"),
                "decision_counts":   dict(dec_count),
            },
        })
    return rows


def build_outcome_row(o: dict) -> dict:
    """1 outcome ledger → 1 row v4_outcomes (WIDE 1-1)."""
    return {
        "pred_id":                   o.get("pred_id"),
        "symbol":                    o.get("symbol"),
        "signal_date":               o.get("signal_date"),
        "snap_time":                 o.get("snap_time"),          # text "HH:MM" khớp ledger
        "eval_date":                 o.get("eval_date"),
        "lens":                      o.get("lens") or "trade",
        "scoring_version":           o.get("scoring_version"),
        "scoring_version_effective": o.get("scoring_version_effective"),
        "decision":                  o.get("decision"),
        "confidence":                o.get("confidence"),
        "total_score":               _num(o.get("total_score")),
        "t0_close":                  _num(o.get("t0_close")),
        "n_bars":                    o.get("n_bars"),
        "ret_1d":                    _num(o.get("ret_1d")),
        "ret_3d":                    _num(o.get("ret_3d")),
        "ret_5d":                    _num(o.get("ret_5d")),
        "ret_10d":                   _num(o.get("ret_10d")),
        "mfe_pct":                   _num(o.get("mfe_pct")),
        "mae_pct":                   _num(o.get("mae_pct")),
        "schema_version":            o.get("schema_version"),
    }


# ── Upsert (PostgREST) ─────────────────────────────────────────────────────────
class Supabase:
    def __init__(self, url: str, key: str):
        self.rest = url.rstrip("/") + "/rest/v1"
        self._h = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> int:
        total = 0
        if requests is None:
            raise RuntimeError("Missing requests dependency for Supabase writes")
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            body = json.dumps(chunk, default=str)
            # Retry backoff cho lỗi TẠM (504/502/503/429 hoặc timeout/mạng).
            last_err = ""
            for attempt in range(1, MAX_RETRY + 1):
                try:
                    r = requests.post(
                        f"{self.rest}/{table}",
                        params={"on_conflict": on_conflict},
                        headers=self._h,
                        data=body,
                        timeout=120,
                    )
                except requests.RequestException as e:
                    last_err = f"network:{type(e).__name__}"
                    r = None
                if r is not None and r.status_code < 300:
                    break
                if r is not None:
                    last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                    # Lỗi client (4xx trừ 429) không đáng retry → dừng ngay.
                    if 400 <= r.status_code < 500 and r.status_code != 429:
                        raise RuntimeError(f"upsert {table} {last_err}")
                if attempt < MAX_RETRY:
                    wait = 2 ** attempt
                    log.warning("  upsert %s batch @%d lỗi (%s) — thử lại sau %ds (lần %d/%d)",
                                table, total, last_err, wait, attempt, MAX_RETRY)
                    time.sleep(wait)
            else:
                raise RuntimeError(f"upsert {table} thất bại sau {MAX_RETRY} lần: {last_err}")
            total += len(chunk)
            log.info("  upsert %s: %d/%d", table, total, len(rows))
        return total

    def delete(self, table: str, filters: dict[str, str]) -> None:
        """Delete a narrowly filtered serving dataset with the same retry policy."""
        if requests is None:
            raise RuntimeError("Missing requests dependency for Supabase writes")
        if not filters:
            raise ValueError("Refusing an unfiltered Supabase delete")
        last_err = ""
        for attempt in range(1, MAX_RETRY + 1):
            try:
                r = requests.delete(
                    f"{self.rest}/{table}",
                    params=filters,
                    headers=self._h,
                    timeout=120,
                )
            except requests.RequestException as e:
                last_err = f"network:{type(e).__name__}"
                r = None
            if r is not None and r.status_code < 300:
                log.info("  delete %s: filtered cleanup complete", table)
                return
            if r is not None:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    raise RuntimeError(f"delete {table} {last_err}")
            if attempt < MAX_RETRY:
                wait = 2 ** attempt
                log.warning("  delete %s lỗi (%s) — thử lại sau %ds (lần %d/%d)",
                            table, last_err, wait, attempt, MAX_RETRY)
                time.sleep(wait)
        raise RuntimeError(f"delete {table} thất bại sau {MAX_RETRY} lần: {last_err}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Mirror ledger JSONL → Supabase (idempotent).")
    ap.add_argument("--months", nargs="*", help="YYYY-MM ... (mặc định: mọi tháng có trong ledger)")
    ap.add_argument("--only", choices=["predictions", "outcomes"], help="chỉ sync 1 nguồn")
    ap.add_argument("--dry-run", action="store_true", help="chỉ transform + đếm, KHÔNG gọi network")
    args = ap.parse_args()

    months = args.months or _months_available()
    if not months:
        log.error("Không tìm thấy tháng ledger nào trong %s / %s", PRED_DIRS, OUTC_DIRS)
        return 1
    log.info("Tháng sync: %s | only=%s | dry_run=%s", months, args.only or "all", args.dry_run)

    # Đọc + transform
    run_rows: list[dict] = []
    sig_rows: list[dict] = []
    out_rows: list[dict] = []

    if args.only != "outcomes":
        preds = [
            p for d in PRED_DIRS for m in months for p in _read_jsonl(d / f"{m}.jsonl")
            if p.get("scoring_version") in REVIEW_VERSIONS
        ]
        sig_rows = [build_signal_row(p) for p in preds]
        run_rows = build_run_rows(preds)
        log.info("predictions: %d rows → %d signals, %d runs", len(preds), len(sig_rows), len(run_rows))

    if args.only != "predictions":
        outs = [
            o for d in OUTC_DIRS for m in months for o in _read_jsonl(d / f"{m}.jsonl")
            if o.get("scoring_version") in REVIEW_VERSIONS
        ]
        out_rows = [build_outcome_row(o) for o in outs]
        log.info("outcomes: %d rows → %d outcome rows", len(outs), len(out_rows))

    if args.dry_run:
        log.info("DRY-RUN: bỏ qua upsert. runs=%d signals=%d outcomes=%d",
                 len(run_rows), len(sig_rows), len(out_rows))
        return 0

    # Env (server-only) — KHÔNG log giá trị
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Thiếu env SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (server-only).")
        return 2

    sb = Supabase(url, key)
    # Thứ tự: runs TRƯỚC signals (FK v4_signals.run_id → v4_runs.run_id).
    if run_rows:
        sb.upsert("v4_runs", run_rows, on_conflict="run_id")
    if sig_rows:
        sb.upsert("v4_signals", sig_rows, on_conflict="symbol,signal_date,snap_time,scoring_version")
    if out_rows:
        sb.upsert("v4_outcomes", out_rows, on_conflict="symbol,signal_date,snap_time,lens,scoring_version")

    log.info("=== SYNC DONE === runs=%d signals=%d outcomes=%d",
             len(run_rows), len(sig_rows), len(out_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
