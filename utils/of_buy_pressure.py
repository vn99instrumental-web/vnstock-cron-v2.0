"""
utils/of_buy_pressure.py
========================
Cờ "Áp lực mua khớp lệnh" (OF buy-pressure) — tách từ order flow NỘI.

Ý tưởng (validated forward, lag-test pass, regime-robust trên 1 cung macro):
    - buy_ratio THEO SỐ LỆNH (buy_count / (buy_count+sell_count)) là tín hiệu
      chính. IC(t+1..t+5) ~ +0.21, MẠNH HƠN buy_ratio theo khối lượng (+0.19).
    - Khối lượng (vol_ma_ratio) và số lần khớp (total_trades) KHÔNG cộng điểm
      (đứng riêng chúng edge ÂM: -0.11 / -0.24). Chúng chỉ làm CỔNG XÁC NHẬN:
        * vol_ma_ratio >= VOL_GATE  → đủ khối lượng để buy_ratio đáng tin
          (IC buy_ratio: 0.15 nhóm KL thấp → 0.21 nhóm KL cao).
        * total_trades >= MIN_TRADES → sàn thanh khoản (loại mã quá ít lệnh).
          Lưu ý: tần suất CAO không phải điểm cộng — buy_ratio còn mạnh hơn ở
          nhóm tần suất thấp; đây chỉ là SÀN, không phải "càng nhiều càng tốt".

Cửa sổ hiệu lực: 3–5 ngày, đảo chiều sau t+3..t+10 → tín hiệu ngắn hạn.

⚠️ TRẠNG THÁI: PRE-REGISTER / INDICATIVE. Toàn bộ ngưỡng dưới đây fit trên
   MỘT cung macro (30/06–24/07/2026, ~19 phiên). IC ~0.2 là cao bất thường →
   rất có thể bị thổi phồng bởi episode này. Cap để NHỎ, quan sát tiền thật,
   chỉ nới sau khi có một cung macro MỚI độc lập xác nhận.

Quan sát in-sample: buy_ratio đơn điệu tăng tới ~0.60–0.65 rồi ĐUỐI ở >0.65
   (-0.84% vs -0.21%). KHÔNG đặt trần cứng 0.65 ở đây (dễ overfit 1 cửa sổ);
   dùng ngưỡng ≥0.55 cho bền, cap nhỏ tự giới hạn thiệt hại phần đuối.
"""

# ── Ngưỡng (tunable — fit 1 cung macro, coi là điểm khởi đầu) ──────────────
BR_BUY      = 0.55   # buy_ratio theo SỐ LỆNH ≥ → áp lực mua
BR_SELL     = 0.45   # buy_ratio theo SỐ LỆNH ≤ → áp lực bán
VOL_GATE    = 1.0    # vol_ma_ratio tối thiểu (cổng xác nhận khối lượng)
MIN_TRADES  = 50     # số lệnh khớp tối thiểu (sàn thanh khoản, KHÔNG phải điểm)
BP_CAP      = 4      # cap nhỏ (thang giống của order-flow/prop hiện có)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def buy_pressure_pts(buy_count, sell_count, total_trades, vol_ma_ratio):
    """
    Trả về điểm cộng/trừ (±BP_CAP hoặc 0) cho cờ áp lực mua khớp lệnh.

    Chỉ bật khi QUA CẢ HAI CỔNG (đủ thanh khoản + đủ khối lượng) và buy_ratio
    theo số lệnh vượt ngưỡng. Mọi input thiếu/None → 0 (an toàn, không đoán).
    """
    bc = _f(buy_count)
    sc = _f(sell_count)
    tt = _f(total_trades)
    vr = _f(vol_ma_ratio)

    # thiếu dữ liệu chiều mua/bán → không kết luận
    if bc is None or sc is None or (bc + sc) <= 0:
        return 0
    # sàn thanh khoản: quá ít lệnh khớp → nhiễu, bỏ
    if tt is None or tt < MIN_TRADES:
        return 0
    # cổng khối lượng: KL không đủ → buy_ratio không đáng tin, bỏ
    if vr is None or vr < VOL_GATE:
        return 0

    br = bc / (bc + sc)          # buy_ratio THEO SỐ LỆNH
    if br >= BR_BUY:
        return BP_CAP
    if br <= BR_SELL:
        return -BP_CAP
    return 0
