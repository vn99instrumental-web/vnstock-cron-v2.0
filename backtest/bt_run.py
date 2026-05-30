"""
bt_run.py — Entrypoint duy nhất cho toàn bộ backtest pipeline
==============================================================
ISOLATION CHECK (chạy trước mọi thứ):
  ✗ Không ghi vào output/
  ✗ Không import utils/, steps/, config.py production
  ✓ Mọi output → backtest_output/

Usage:
  # Full pipeline (build data + evaluate + grid search)
  python backtest/bt_run.py

  # Test nhanh với 10 symbols
  python backtest/bt_run.py --max 10

  # Chỉ evaluate (đã có dataset.parquet)
  python backtest/bt_run.py --skip-build

  # Test nhiều horizon
  python backtest/bt_run.py --skip-build --horizon 1
  python backtest/bt_run.py --skip-build --horizon 3
  python backtest/bt_run.py --skip-build --horizon 5

  # Chỉ xem baseline, không grid search
  python backtest/bt_run.py --skip-build --eval-only
"""
import sys
import logging
import argparse
from pathlib import Path

# ── Setup path ─────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── Isolation guard ─────────────────────────────────────────────────────
def check_isolation() -> None:
    """Đảm bảo không có import nào từ production utils/steps/config."""
    forbidden = ["utils.cache", "utils.helpers", "steps.", "config"]
    for mod in list(sys.modules.keys()):
        for f in forbidden:
            if mod.startswith(f):
                raise RuntimeError(
                    f"ISOLATION VIOLATION: module '{mod}' đã được import.\n"
                    "Backtest không được dùng production modules."
                )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def print_banner():
    log.info("=" * 60)
    log.info("  VNStock Backtest Pipeline")
    log.info("  Output: backtest_output/  (không đụng output/)")
    log.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="VNStock backtest — isolated từ production flow"
    )
    parser.add_argument(
        "--max", type=int, default=None,
        help="Giới hạn số symbols để test nhanh (vd: --max 10)"
    )
    parser.add_argument(
        "--skip-build", action="store_true",
        help="Bỏ qua bước fetch data, dùng dataset.parquet đã có"
    )
    parser.add_argument(
        "--horizon", type=int, default=5, choices=[1, 3, 5],
        help="Forward return horizon (days): 1, 3, hoặc 5 (mặc định: 5)"
    )
    parser.add_argument(
        "--threshold", type=int, default=20,
        help="Score threshold để tính hit rate (mặc định: 20)"
    )
    parser.add_argument(
        "--eval-only", action="store_true",
        help="Chỉ evaluate baseline, bỏ qua grid search"
    )
    parser.add_argument(
        "--all-horizons", action="store_true",
        help="Chạy evaluate cho cả 3 horizons (1d, 3d, 5d)"
    )
    args = parser.parse_args()

    print_banner()
    check_isolation()

    # ── Step 1: Build dataset ───────────────────────────────────────────
    if not args.skip_build:
        log.info("\n[Step 1/2] Building historical dataset...")
        log.info("  Fetch OHLCV từ VCI → tính TA → label forward returns")
        log.info("  Ước tính: 150 symbols × ~250 ngày ≈ 37,500 rows")
        log.info("  Thời gian: ~5-10 phút (rate limited)")

        from backtest.bt_data import build_dataset
        dataset = build_dataset(max_symbols=args.max)

        if dataset.empty:
            log.error("Dataset trống — dừng.")
            sys.exit(1)

        log.info(f"  ✓ Dataset: {len(dataset):,} rows")
    else:
        log.info("\n[Step 1/2] Skipped (--skip-build)")
        dataset_path = REPO_ROOT / "backtest_output" / "dataset.parquet"
        if not dataset_path.exists():
            log.error(
                f"Dataset không tìm thấy: {dataset_path}\n"
                "Chạy lần đầu không có --skip-build để build data."
            )
            sys.exit(1)
        log.info(f"  Dataset tồn tại: {dataset_path}")

    # ── Step 2: Evaluate ────────────────────────────────────────────────
    log.info("\n[Step 2/2] Evaluating...")
    from backtest.bt_evaluate import main as run_evaluate

    horizons = [1, 3, 5] if args.all_horizons else [args.horizon]

    for h in horizons:
        log.info(f"\n  → Horizon: {h}d")
        run_evaluate(
            horizon   = h,
            threshold = args.threshold,
            eval_only = args.eval_only,
        )

    # ── Summary ─────────────────────────────────────────────────────────
    reports_dir = REPO_ROOT / "backtest_output" / "reports"
    log.info(f"\n{'='*60}")
    log.info("  BACKTEST COMPLETE")
    log.info(f"  Reports: {reports_dir}")
    log.info(f"  Files:")
    if reports_dir.exists():
        for f in sorted(reports_dir.iterdir()):
            log.info(f"    {f.name}")
    log.info(f"\n  Bước tiếp theo:")
    log.info(f"    1. Đọc summary_h5.txt → xem group nào predictive")
    log.info(f"    2. Đọc grid_caps_h5.csv → chọn best caps")
    log.info(f"    3. Update CURRENT_CAPS trong backtest/bt_config.py")
    log.info(f"    4. Apply vào steps/step_scoring.py GROUP_CAPS")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
