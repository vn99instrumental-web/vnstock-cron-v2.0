# scripts/diag_universe_industries.py
# ============================================================================
# PHÂN NHÓM NGÀNH cho rổ 130 mã (READ-ONLY) — chuẩn bị cho Phương án 3:
#   chủ đề HẸP (≤ N mã)  → đi vào luồng gắn mã
#   ngành RỘNG (> N mã)  → nhánh song song "nhiệt độ ngành", KHÔNG cộng vào điểm mã
#
# Script trả lời 3 câu hỏi:
#   1. Rổ 130 mã phân bổ vào những ngành nào, mỗi ngành bao nhiêu mã?
#   2. Ngưỡng RỘNG/HẸP nên đặt ở đâu (nhìn phân bố thật, không đoán)?
#   3. Nhãn ngành nào KHÔNG khớp khóa trong INDUSTRY_KEYWORDS → mã thuộc
#      ngành đó vĩnh viễn không nhận được điểm ngành (lỗi PNJ).
#
# KHÔNG ghi file. Chạy: debug.yml → script = scripts/diag_universe_industries.py
# ============================================================================
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("VNSTOCK_INTERACTIVE", "0")
os.environ.setdefault("MPLCONFIGDIR", "/home/runner/.config/matplotlib")

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger("universe_ind")

from utils.cache import load_json
from utils.industry_keywords import INDUSTRY_KEYWORDS

# Ngưỡng thử — script in phân bố để anh quyết ngưỡng cuối
TRIAL_THRESHOLDS = (2, 3, 5, 8)


def run():
    # ── Universe + nhãn ngành ──
    # Ưu tiên v2f_signals (có sẵn field industry đã dùng trong scoring —
    # ĐÚNG chuỗi mà consumer tra cứu), fallback ranking + industry_map
    signals = load_json("v2f_signals.json") or []
    sym_ind: dict[str, str] = {}
    src = ""

    if signals:
        for r in signals:
            s = r.get("symbol")
            if s:
                sym_ind[s] = (r.get("industry") or "").strip()
        src = "v2f_signals.json (field 'industry' — đúng chuỗi consumer dùng)"

    if not sym_ind:
        ranking = load_json("v2f_ranking.json") or []
        universe = {r.get("symbol") for r in ranking if isinstance(r, dict)}
        imap = load_json("market/industry_map.json") or load_json("industry_map.json") or []
        for r in imap:
            s = r.get("symbol") or r.get("ticker") or r.get("code")
            if s in universe:
                sym_ind[s] = (r.get("icb_name") or "").strip()
        src = "v2f_ranking.json + industry_map.json"

    if not sym_ind:
        log.error("Không load được universe — cần v2f_signals.json hoặc "
                  "v2f_ranking.json + industry_map.json")
        return 1

    log.info(f"=== PHÂN NHÓM NGÀNH — rổ {len(sym_ind)} mã ===")
    log.info(f"Nguồn nhãn ngành: {src}")

    # ── Đếm theo ngành ──
    by_ind: dict[str, list[str]] = {}
    for s, ind in sym_ind.items():
        by_ind.setdefault(ind or "(TRỐNG)", []).append(s)
    for v in by_ind.values():
        v.sort()

    rows = sorted(by_ind.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    keys = set(INDUSTRY_KEYWORDS.keys())

    log.info("─" * 100)
    log.info(f"{'#mã':>4}  {'KHỚP':5s} {'NGÀNH (nhãn thật trong dữ liệu)':45s} mã")
    log.info("─" * 100)
    n_broken_sym = 0
    broken_inds = []
    for ind, syms in rows:
        ok = ind in keys
        if not ok and ind != "(TRỐNG)":
            n_broken_sym += len(syms)
            broken_inds.append((ind, len(syms)))
        mark = "OK   " if ok else "LỆCH "
        log.info(f"{len(syms):>4}  {mark} {ind[:45]:45s} "
                 f"{', '.join(syms[:8])}{' ...' if len(syms) > 8 else ''}")

    # ── Phân bố + thử ngưỡng ──
    log.info("═" * 100)
    sizes = [len(s) for _, s in rows]
    log.info(f"Tổng: {len(rows)} ngành | lớn nhất {max(sizes)} mã | "
             f"trung vị {sorted(sizes)[len(sizes)//2]} mã | "
             f"{sum(1 for x in sizes if x == 1)} ngành chỉ có 1 mã")
    log.info("Thử ngưỡng RỘNG/HẸP:")
    for t in TRIAL_THRESHOLDS:
        wide   = [(i, len(s)) for i, s in rows if len(s) > t]
        n_wide_sym = sum(n for _, n in wide)
        log.info(f"  ngưỡng >{t} mã = RỘNG → {len(wide)} ngành rộng "
                 f"({n_wide_sym}/{len(sym_ind)} mã = "
                 f"{n_wide_sym/len(sym_ind)*100:.0f}% rổ đi nhánh song song) "
                 f"| {len(rows)-len(wide)} ngành hẹp")

    # ── Lỗi lệch tên ngành ──
    log.info("═" * 100)
    if broken_inds:
        log.info(f"⚠️ LỆCH TÊN: {len(broken_inds)} ngành KHÔNG có khóa trong "
                 f"INDUSTRY_KEYWORDS → {n_broken_sym}/{len(sym_ind)} mã "
                 f"({n_broken_sym/len(sym_ind)*100:.0f}%) vĩnh viễn không nhận điểm ngành:")
        for ind, n in sorted(broken_inds, key=lambda x: -x[1]):
            near = [k for k in keys
                    if k.lower() in ind.lower() or ind.lower() in k.lower()]
            hint = f"  ← khóa gần giống: {near}" if near else "  ← không có khóa nào gần"
            log.info(f"     {n:>3} mã  '{ind}'{hint}")
    else:
        log.info("✅ Mọi nhãn ngành đều khớp khóa INDUSTRY_KEYWORDS")

    # Chiều ngược lại: khóa có trong keywords nhưng không mã nào thuộc
    unused = sorted(keys - set(by_ind.keys()))
    log.info(f"Khóa INDUSTRY_KEYWORDS không mã nào trong rổ dùng tới: "
             f"{len(unused)}/{len(keys)}")
    if unused:
        log.info(f"     {', '.join(unused[:20])}{' ...' if len(unused) > 20 else ''}")

    log.info("READ-ONLY DONE — không file nào bị ghi/commit")
    return 0


if __name__ == "__main__":
    sys.exit(run())
