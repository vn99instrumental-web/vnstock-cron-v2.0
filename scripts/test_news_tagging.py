# scripts/test_news_tagging.py
# ============================================================================
# Test offline cho utils/news_tagging.py — KHÔNG cần mạng.
# Verify ĐỊNH TUYẾN (mã nào nhận điểm), không verify hướng sentiment.
# Chạy: python scripts/test_news_tagging.py  |  hoặc debug.yml
# ============================================================================
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.news_sentiment import score_sentiment
from utils.news_tagging import build_context, tag_article, aggregate, TICKER_BOOST
from utils.sector_topics import TOPIC_DECAY

# ── Context giả lập (universe nhỏ + tên công ty) ──
UNIVERSE = ["PNJ", "HPG", "HSG", "NKG", "GAS", "BSR", "VCB", "TNG",
            "ANV", "VHC", "BAF", "DBC", "HAG", "GMD", "VSC", "DXP"]
IMAP = [
    {"symbol": "PNJ", "organ_name": "Công ty CP Vàng bạc Đá quý Phú Nhuận", "organ_short_name": "Phú Nhuận"},
    {"symbol": "HPG", "organ_name": "Công ty CP Tập đoàn Hòa Phát", "organ_short_name": "Hòa Phát"},
    {"symbol": "GAS", "organ_name": "Tổng Công ty Khí Việt Nam", "organ_short_name": "PV GAS"},
    {"symbol": "VCB", "organ_name": "Ngân hàng TMCP Ngoại thương Việt Nam", "organ_short_name": "Vietcombank"},
    {"symbol": "VHC", "organ_name": "Công ty CP Vĩnh Hoàn", "organ_short_name": "Vĩnh Hoàn"},
]
CTX = build_context(UNIVERSE, IMAP)


def _mk(title, desc=""):
    """Bài với sentiment thật + source/decay = 1 để dễ đọc điểm."""
    art = {"title": title, "short_description": desc, "tags": "",
           "source_weight": 1.0, "time_decay": 1.0}
    art["raw_sentiment"] = score_sentiment(f"{title} {desc}")
    return art


# (title, expect_direct: set, expect_topic_syms: set, expect_heat_sectors: set)
CASES = [
    # ── Đích danh ──
    ("Hòa Phát báo lãi kỷ lục quý II",
     {"HPG"}, set(), set()),
    ("PNJ giãn tiến độ thanh toán thu mua kim cương",
     {"PNJ"}, set(), set()),          # PNJ đích danh; "kim cương" KHÔNG cộng thêm (R1)

    # ── Chủ đề, không đích danh → topic ×0.6 ──
    ("Bộ Công Thương kiểm tra kinh doanh vàng bạc, kim cương, đá quý",
     set(), {"PNJ"}, set()),
    ("Giá thép xây dựng tăng tuần thứ ba",
     set(), {"HPG", "HSG", "NKG"}, set()),
    ("Giá heo hơi lập đỉnh",
     set(), {"BAF", "DBC", "HAG"}, set()),

    # ── Chủ đề nhiều nhóm hẹp (R2: mỗi nhóm ×0.6 độc lập) ──
    ("Giá thép và giá cao su cùng tăng mạnh",
     set(), {"HPG", "HSG", "NKG", "GVR", "PHR"}, set()),   # 2 nhóm hẹp, mỗi nhóm ×0.6

    # ── Đích danh + chủ đề cùng nhóm (R1: chỉ direct, không chồng) ──
    ("Vĩnh Hoàn hưởng lợi khi xuất khẩu cá tra phục hồi",
     {"VHC"}, {"ANV"}, set()),   # VHC đích danh (full name) → direct; ANV cùng nhóm → topic

    # ── Nhóm rộng → heat, KHÔNG vào điểm mã ──
    ("Ngành ngân hàng đón mùa báo lãi quý II",
     set(), set(), {"ngan_hang"}),

    # ── Không thuộc nhóm nào ──
    ("VN-Index tăng hơn 10 điểm phiên đầu tuần",
     set(), set(), set()),
    ("Giá vàng SJC vượt 80 triệu đồng mỗi lượng",
     set(), set(), set()),       # "vàng" trần bị chặn
]


def _run_cases() -> int:
    n_pass = n_fail = 0
    for title, exp_direct, exp_topic, exp_heat in CASES:
        art = _mk(title)
        r = tag_article(art, CTX)
        got_direct = set(r["symbol_direct"].keys())
        got_topic  = set(r["symbol_topic"].keys())
        got_heat   = set(r["sector_heat"].keys())

        ok = (got_direct == exp_direct
              and got_topic == exp_topic
              and got_heat == exp_heat)
        n_pass += ok
        n_fail += (not ok)
        print(f"{'PASS' if ok else 'FAIL'}  {title[:58]}")
        if not ok:
            print(f"      direct: got {got_direct} exp {exp_direct}")
            print(f"      topic : got {got_topic} exp {exp_topic}")
            print(f"      heat  : got {got_heat} exp {exp_heat}")
        else:
            ev = r["evidence"]
            detail = []
            if got_direct: detail.append(f"direct={sorted(got_direct)}")
            if got_topic:  detail.append(f"topic={sorted(got_topic)}×{TOPIC_DECAY}")
            if got_heat:   detail.append(f"heat={sorted(got_heat)}")
            if detail: print(f"      → {' | '.join(detail)}")
    return n_fail


def _test_overlap_no_double():
    """R1: bài đích danh PNJ + có 'kim cương' → PNJ chỉ tính 1 lần (direct)."""
    art = _mk("PNJ và ngành kim cương gặp khó về thanh khoản")
    art["raw_sentiment"] = -2.0   # ép âm để kiểm giá trị
    r = tag_article(art, CTX)
    assert "PNJ" in r["symbol_direct"], "PNJ phải ở direct"
    assert "PNJ" not in r["symbol_topic"], "R1: PNJ KHÔNG được ở topic khi đã direct"
    print("PASS  R1 overlap: PNJ chỉ tính direct, không cộng chồng topic")


def _test_ticker_boost():
    art = _mk("HPG tăng trần")
    art["raw_sentiment"] = 2.0
    r = tag_article(art, CTX)
    # base = 2.0 × 1 × 1 = 2.0 ; ticker boost ×1.5 = 3.0
    assert abs(r["symbol_direct"]["HPG"] - 3.0) < 1e-6, r["symbol_direct"]
    print(f"PASS  ticker boost ×{TICKER_BOOST}: HPG = {r['symbol_direct']['HPG']}")


def _test_aggregate_mean():
    """2 bài về HPG → điểm = trung bình, không phải tổng."""
    a1 = _mk("HPG báo lãi"); a1["raw_sentiment"] = 2.0
    a2 = _mk("HPG mở rộng nhà máy"); a2["raw_sentiment"] = 1.0
    agg = aggregate([a1, a2], CTX)
    # mỗi bài: 2.0×1.5=3.0 và 1.0×1.5=1.5 → mean = 2.25
    assert abs(agg["symbol_score"]["HPG"] - 2.25) < 1e-6, agg["symbol_score"]
    print(f"PASS  aggregate mean: HPG(2 bài) = {agg['symbol_score']['HPG']}")


def main() -> int:
    print("─" * 80)
    fails = _run_cases()
    print("─" * 80)
    _test_overlap_no_double()
    _test_ticker_boost()
    _test_aggregate_mean()
    print("─" * 80)
    if fails == 0:
        print("✅ ALL TAGGING TESTS PASS")
        return 0
    print(f"❌ {fails} case FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
