-- 0016_marginal_ic.sql — Bảng đóng góp BIÊN của chỉ báo con (hồi quy đa biến).
--
-- Do scripts/analyze_marginal_ic.py ghi (upsert). Tách đóng góp riêng từng chỉ
-- báo khi đã kiểm soát các chỉ báo còn lại (khử trùng lặp tín hiệu) — để combine
-- version mới. Cross-sectional OLS, demean trong ngày, chuẩn hoá; per version.
-- Ước lượng tham chiếu, KHÔNG phải IC chính thức evaluator.
--
-- coef      = hệ số hồi quy chuẩn hoá (đóng góp biên, cùng thang IC).
-- tstat     = độ tin (|t|≥2 ~ có ý nghĩa thống kê).
-- univar_ic = IC đơn biến (Spearman) của chính chỉ báo đó — để đối chiếu corr↔biên.
-- indicator = '_model_r2' → dòng đặc biệt: coef = R² mô hình, n = số quan sát.

create table if not exists public.v4_marginal_ic (
  version   text    not null,
  indicator text    not null,
  factor    text,
  horizon   int     not null,
  coef      numeric,
  tstat     numeric,
  univar_ic numeric,
  n         int,
  primary key (version, indicator, horizon)
);

grant select on public.v4_marginal_ic to anon, authenticated;
