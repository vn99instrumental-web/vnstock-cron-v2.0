# scripts/test_news_sentiment.py
# ============================================================================
# Test offline cho utils/news_sentiment.py — KHÔNG cần mạng, KHÔNG cần vnstock.
# Chạy local:            python scripts/test_news_sentiment.py
# Chạy qua debug.yml:    script = scripts/test_news_sentiment.py
#
# Mỗi case: (tiêu đề mẫu, dấu kỳ vọng)  với dấu ∈ {"+", "-", "0"}
# Pass = dấu của điểm khớp dấu kỳ vọng. Exit code 1 nếu có case fail.
# ============================================================================
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.news_sentiment import score_sentiment

CASES: list[tuple[str, str]] = [
    # ── Hướng đúng của lãi suất (cơ chế cũ chấm sai) ──
    ("NHNN giảm lãi suất điều hành thêm 0,5 điểm phần trăm",            "+"),
    ("Fed tăng lãi suất, thị trường chịu áp lực",                        "-"),

    # ── KQKD ──
    ("Lợi nhuận quý II của Hòa Phát giảm 30% so với cùng kỳ",            "-"),
    ("Vietcombank báo lãi kỷ lục trong quý II",                          "+"),
    ("FPT báo lãi 9 tháng tăng 20%",                                     "+"),
    ("Doanh nghiệp thép báo lỗ quý thứ ba liên tiếp",                    "-"),
    ("Công ty không còn thua lỗ sau tái cấu trúc",                       "+"),
    ("Doanh nghiệp thoát lỗ sau 3 quý",                                  "+"),
    ("Biên lợi nhuận giảm nhẹ do giá nguyên liệu",                       "-"),

    # ── Sự kiện mạnh ──
    ("Chủ tịch tập đoàn bị khởi tố về tội thao túng chứng khoán",        "-"),
    ("Cổ phiếu XYZ vào diện kiểm soát từ ngày 1/8",                      "-"),
    ("HOSE hủy niêm yết bắt buộc cổ phiếu ABC",                          "-"),
    ("DIG trúng thầu dự án hạ tầng 2.000 tỷ đồng",                       "+"),
    ("Công ty vượt kế hoạch năm chỉ sau 6 tháng",                        "+"),

    # ── Hành động cổ đông / cổ tức ──
    ("Cổ đông lớn đăng ký bán 5 triệu cổ phiếu",                          "-"),
    ("Thành viên HĐQT đăng ký mua 2 triệu cổ phiếu",                      "+"),
    ("MWG chốt quyền cổ tức tiền mặt tỷ lệ 10%",                          "+"),
    ("Doanh nghiệp hoãn cổ tức do khó khăn dòng tiền",                    "-"),

    # ── Từ đơn chung chung phải = 0 (thiết kế mới) ──
    ("Giá thép giảm mạnh trong tuần qua",                                 "0"),
    ("VN-Index tăng hơn 10 điểm phiên đầu tuần",                          "0"),
    ("Thị trường chứng khoán hôm nay diễn biến giằng co",                 "0"),

    # ── Phủ định ──
    ("Doanh nghiệp khó tăng trưởng lợi nhuận trong năm nay",              "-"),

    # ── Gap matching: chủ thể + hướng tách nhau ──
    ("Doanh thu Vinamilk quý II giảm 5% so với cùng kỳ",                  "-"),
    ("Lợi nhuận trước thuế của ACB tăng 15% trong quý II",                "+"),
    ("Công ty lỗ hơn 200 tỷ đồng trong quý II",                           "-"),
    ("Biên lợi nhuận gộp quý này thu hẹp đáng kể",                        "-"),

    # ── Mild ──
    ("Ngành dệt may hưởng lợi từ hiệp định thương mại mới",               "+"),
    ("Doanh nghiệp xi măng đối mặt áp lực chi phí đầu vào",               "-"),
]


def _sign(x: float) -> str:
    if x > 0:  return "+"
    if x < 0:  return "-"
    return "0"


def main() -> int:
    n_pass = 0
    n_fail = 0
    print(f"{'KQ':<4} {'điểm':>6}  {'kỳ vọng':<8} tiêu đề / cụm match")
    print("-" * 100)
    for title, expected in CASES:
        score, evidence = score_sentiment(title, return_evidence=True)
        got = _sign(score)
        ok  = (got == expected)
        n_pass += ok
        n_fail += (not ok)
        ev = ", ".join(f"{p}({s:+.1f})" for p, s in evidence) or "(no match)"
        print(f"{'PASS' if ok else 'FAIL':<4} {score:>+6.1f}  "
              f"{expected:<8} {title}")
        print(f"{'':<20} → {ev}")
    print("-" * 100)
    print(f"TOTAL: {n_pass} pass / {n_fail} fail / {len(CASES)} cases")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
