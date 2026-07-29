#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cleanup_legacy.py
=========================
Dọn code legacy V1 + V2 khỏi repo vnstock-cron-v2.0, GIỮ nguyên hệ V2F (v2.3 + v3 shadow).

MẶC ĐỊNH = DRY-RUN: chỉ LIỆT KÊ file sẽ xóa, KHÔNG đụng gì.
Xóa thật     :  python scripts/cleanup_legacy.py --apply
Gồm docs cũ  :  python scripts/cleanup_legacy.py --include-docs [--apply]
Khôi phục    :  python scripts/cleanup_legacy.py --restore .cleanup_backup/legacy_XXXX.zip

AN TOÀN 3 LỚP:
  1) PROTECTED   — chặn cứng: nếu vô tình có file bẫy trong danh sách xóa -> DỪNG.
  2) Quét import — nếu file ĐANG DÙNG import module sắp xóa -> DỪNG, không xóa gì.
  3) Auto-backup — khi --apply, tự nén file sắp xóa thành .cleanup_backup/legacy_<ts>.zip
                   TRƯỚC khi xóa (tắt bằng --no-backup, KHÔNG khuyến nghị).

LƯU Ý VẬN HÀNH: TRƯỚC khi --apply, hãy TẮT 2 workflow legacy
(cron_intraday.yml, cron_intraday_v2.yml) trong tab Actions, nếu không chúng
sẽ chạy và fail đỏ mỗi ngày sau khi file .py bị xóa.
"""

from __future__ import annotations
import argparse
import datetime as _dt
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# ── Xác định gốc repo: script nằm ở scripts/ -> gốc = thư mục cha ─────────────
ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / ".cleanup_backup"

# ── DANH SÁCH XÓA (đã verify bằng import graph, an toàn) ──────────────────────
DELETE_V1 = [
    ".github/workflows/cron_intraday.yml",
    "steps/step_context_refresh.py",
    "steps/step_snapshot.py",
    "steps/step_order_flow.py",
    "steps/step_scoring.py",
    "steps/step_record_predictions.py",
    "steps/step1_ranking.py",
    "steps/step2_deep.py",
    "steps/step_all.py",
    "steps/analyze_performance.py",
    "steps/step3_context_get_market_context.py",  # mồ côi
    "steps/step_scoring_context_block.py",         # mồ côi
]

DELETE_V2 = [
    ".github/workflows/cron_intraday_v2.yml",
    "steps/step_snapshot_v2.py",
    "steps/step_order_flow_v2.py",
    "steps/step_scoring_v2.py",
    "steps/step_price_levels_v2.py",
    "steps/step_record_predictions_v2.py",
    "utils/universe_v2.py",
    "scripts/diag_universe_v2.py",
]

DELETE_NEWS_OLD = [
    "steps/step_news_collect.py",
    "utils/news_aggregate.py",
    "utils/news_enrich.py",
]

# Docs cũ — CHỈ xóa khi có cờ --include-docs (cần xác nhận n8n push vào đâu trước).
DELETE_DOCS = [
    "docs/index.html",
    "docs/indexv2.html",
]

# ── BẤT KHẢ XÂM PHẠM (chặn cứng — trông giống legacy nhưng V2F đang dùng) ─────
PROTECTED = {
    "steps/step_price_levels.py",   # v2f_step_price_levels(.v3) import
    "steps/step_finance_scan.py",   # cron_daily + v2f_step_snapshot dùng chung
    "steps/step3_context.py",       # cron_daily
    "steps/step_news_daily.py",     # cron_news (news hiện tại)
    "utils/news_rss.py",            # step_news_daily import
    "docs/indexv3.html",            # dashboard v3 hiện tại
}


# ── Tiện ích ──────────────────────────────────────────────────────────────────
def _fmt_size(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.0f}{unit}"
        nbytes /= 1024
    return f"{nbytes:.1f}TB"


def module_ids(rel_path: str):
    """'steps/step_scoring.py' -> ('steps','step_scoring'). None nếu không phải .py trong pkg."""
    p = Path(rel_path)
    if p.suffix != ".py" or len(p.parts) != 2 or p.parts[0] not in ("steps", "utils", "backtest"):
        return None
    return p.parts[0], p.stem


def import_safety_scan(delete_rel_paths: list[str]) -> list[str]:
    """Quét mọi .py ĐANG GIỮ, tìm import trỏ tới module sắp xóa. Trả danh sách vi phạm."""
    delete_set = set(delete_rel_paths)
    targets = [m for m in (module_ids(rp) for rp in delete_rel_paths) if m]
    violations: list[str] = []
    for pyfile in ROOT.rglob("*.py"):
        rel = pyfile.relative_to(ROOT).as_posix()
        if rel.startswith(".git/") or rel.startswith(".cleanup_backup/") or rel in delete_set:
            continue
        try:
            text = pyfile.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pkg, stem in targets:
            pats = [
                rf"from\s+{pkg}\.{stem}\s+import",
                rf"import\s+{pkg}\.{stem}(?:\s|,|$)",
                rf"from\s+{pkg}\s+import\s+\(?[^)]*\b{stem}\b",
            ]
            if any(re.search(p, text, re.MULTILINE | re.DOTALL) for p in pats):
                violations.append(f"{rel}  ->  {pkg}.{stem}")
    return violations


def ensure_gitignore():
    """Thêm .cleanup_backup/ vào .gitignore nếu chưa có (để không commit nhầm backup)."""
    gi = ROOT / ".gitignore"
    line = ".cleanup_backup/"
    try:
        existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if line not in existing.splitlines():
            with gi.open("a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(f"{line}\n")
            print(f"   ↳ Đã thêm '{line}' vào .gitignore")
    except Exception as e:  # noqa
        print(f"   ⚠️  Không ghi được .gitignore ({e}) — backup vẫn tạo bình thường.")


def make_backup(existing_targets: list[str]) -> Path:
    """Nén các file sắp xóa thành 1 zip có timestamp. Trả về đường dẫn zip."""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = BACKUP_DIR / f"legacy_{ts}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in existing_targets:
            zf.write(ROOT / rel, arcname=rel)  # giữ nguyên đường dẫn tương đối
    return zip_path


def git_rm_or_unlink(rel: str) -> str:
    """Thử 'git rm'; không được thì unlink thường. Trả về nhãn kết quả."""
    try:
        r = subprocess.run(["git", "rm", "--quiet", "--", rel],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            return "git rm"
    except FileNotFoundError:
        pass
    try:
        (ROOT / rel).unlink()
        return "unlink"
    except FileNotFoundError:
        return "missing"
    except Exception as e:  # noqa
        return f"LỖI:{e}"


def do_restore(zip_arg: str) -> int:
    """Bung 1 zip backup trở lại repo (ghi đè file cùng đường dẫn)."""
    zpath = Path(zip_arg)
    if not zpath.is_absolute():
        zpath = (ROOT / zip_arg) if (ROOT / zip_arg).exists() else Path.cwd() / zip_arg
    if not zpath.exists():
        print(f"❌ Không tìm thấy file backup: {zip_arg}")
        # gợi ý các bản backup có sẵn
        if BACKUP_DIR.exists():
            zips = sorted(BACKUP_DIR.glob("legacy_*.zip"))
            if zips:
                print("   Các bản backup hiện có:")
                for z in zips:
                    print(f"     - .cleanup_backup/{z.name}")
        return 2
    print(f"↩️  Khôi phục từ: {zpath}")
    with zipfile.ZipFile(zpath, "r") as zf:
        members = zf.namelist()
        zf.extractall(ROOT)
    for m in members:
        print(f"   ✔ {m}")
    print(f"\nĐã bung {len(members)} file về repo.")
    print("Tiếp theo:  git add -A  ->  git commit -m 'revert: restore legacy files'")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Dọn legacy V1+V2, giữ V2F. Có backup/restore.")
    ap.add_argument("--apply", action="store_true", help="Xóa thật (mặc định chỉ dry-run).")
    ap.add_argument("--include-docs", action="store_true", help="Xóa thêm docs cũ index/indexv2.")
    ap.add_argument("--no-backup", action="store_true", help="(KHÔNG khuyến nghị) bỏ auto-backup zip.")
    ap.add_argument("--no-verify", action="store_true", help="(KHÔNG khuyến nghị) bỏ quét import.")
    ap.add_argument("--restore", metavar="ZIP", help="Bung 1 file backup .zip trở lại repo.")
    args = ap.parse_args()

    # Chế độ khôi phục — chạy độc lập, thoát sớm.
    if args.restore:
        return do_restore(args.restore)

    groups = [
        ("V1 (cron_intraday gốc)", DELETE_V1),
        ("V2 (cron_intraday_v2)", DELETE_V2),
        ("News cũ (đã thay step_news_daily)", DELETE_NEWS_OLD),
    ]
    if args.include_docs:
        groups.append(("Docs cũ (--include-docs)", DELETE_DOCS))
    all_targets = [rel for _, items in groups for rel in items]

    # Lớp an toàn 1: chặn cứng file bất khả xâm phạm
    clash = PROTECTED.intersection(all_targets)
    if clash:
        print("❌ DỪNG: danh sách xóa chứa file BẤT KHẢ XÂM PHẠM:")
        for c in sorted(clash):
            print(f"   - {c}")
        return 2

    print("=" * 70)
    print(f"  CLEANUP LEGACY — gốc repo: {ROOT}")
    print(f"  Chế độ: {'⚠️  XÓA THẬT (--apply)' if args.apply else '🔎 DRY-RUN (không xóa)'}")
    print("=" * 70)

    total_found, total_bytes = 0, 0
    existing_targets: list[str] = []
    for title, items in groups:
        print(f"\n### {title}")
        for rel in items:
            path = ROOT / rel
            if path.exists():
                size = path.stat().st_size
                total_found += 1
                total_bytes += size
                existing_targets.append(rel)
                print(f"   [x] {rel:<52} {_fmt_size(size):>8}")
            else:
                print(f"   [ ] {rel:<52} {'(đã không còn)':>12}")
    print(f"\nTổng: {total_found} file tồn tại sẽ bị xóa, ~{_fmt_size(total_bytes)}.")

    # Lớp an toàn 2: quét import
    if not args.no_verify:
        print("\n--- Quét an toàn: có file ĐANG GIỮ nào import file sắp xóa? ---")
        violations = import_safety_scan(all_targets)
        if violations:
            print("❌ DỪNG — phát hiện import từ file đang giữ (KHÔNG xóa gì):")
            for v in violations:
                print(f"   ⚠️  {v}")
            print("\n   => Kiểm tra lại. Nếu chắc chắn, dùng --no-verify.")
            return 3
        print("✅ An toàn: không file đang giữ nào import các file sắp xóa.")
    else:
        print("\n⚠️  Đã BỎ QUA quét import (--no-verify).")

    if not args.apply:
        print("\n🔎 DRY-RUN xong. Chưa xóa gì.")
        if not args.no_backup:
            print("   Khi chạy --apply: sẽ tự backup vào .cleanup_backup/legacy_<timestamp>.zip trước khi xóa.")
        print("   Chạy lại kèm --apply để xóa thật.")
        return 0

    # Lớp an toàn 3: auto-backup TRƯỚC khi xóa
    if not args.no_backup and existing_targets:
        print("\n📦 Đang backup trước khi xóa...")
        ensure_gitignore()
        zip_path = make_backup(existing_targets)
        rel_zip = zip_path.relative_to(ROOT).as_posix()
        print(f"   ↳ Đã lưu {len(existing_targets)} file -> {rel_zip} ({_fmt_size(zip_path.stat().st_size)})")
        print(f"   ↳ Khôi phục nếu sai:  python scripts/cleanup_legacy.py --restore {rel_zip}")
    else:
        print("\n⚠️  BỎ backup (--no-backup).")

    print("\n⚠️  Đang xóa...")
    done, missing, failed = 0, 0, 0
    for rel in all_targets:
        result = git_rm_or_unlink(rel)
        if result in ("git rm", "unlink"):
            print(f"   ✔ {rel}  ({result})")
            done += 1
        elif result == "missing":
            missing += 1
        else:
            print(f"   ✘ {rel}  [{result}]")
            failed += 1
    print(f"\nKết quả: xóa {done}, bỏ qua {missing} (đã không còn), lỗi {failed}.")
    print("Tiếp theo:  git status  ->  git commit -m 'chore: remove legacy V1+V2'  ->  git push")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
