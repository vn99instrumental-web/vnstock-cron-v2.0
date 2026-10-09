-- Giảm chi phí lọc tín hiệu theo scoring version cho các view IC breakdown.
create index if not exists idx_v4_signals_scoring_version
  on public.v4_signals (scoring_version);