-- 0002_outcomes_wide.sql — Đổi v4_outcomes sang WIDE khớp ledger (ADR-002)
-- Postgres 17 · project mcaqnaomzoqgxccdgvls
--
-- Lý do: ledger v2f_outcomes_v4/*.jsonl lưu WIDE — mỗi prediction 1 row chứa
--   ret_1d/3d/5d/10d + mfe/mae + t0_close/n_bars + eval_date + lens. 100% rows
--   đủ 20 field (evidence: 12.794 rows 2026-08). Migration 0001 (long: horizon+ret)
--   SAI 2 chỗ: (1) ledger không có cột horizon; (2) unique thiếu snap_time → nhiều
--   snap/ngày (5×/ngày) sẽ đè nhau. Bảng đang 0 rows → drop & recreate an toàn.

drop table if exists public.v4_outcomes cascade;

create table public.v4_outcomes (
  id                        bigint generated always as identity primary key,
  pred_id                   text,
  symbol                    text not null,
  signal_date               date not null,
  snap_time                 text not null,            -- "HH:MM" khớp ledger (join theo signals)
  eval_date                 date,
  lens                      text not null default 'trade',
  scoring_version           text,
  scoring_version_effective text,
  decision                  text,                     -- NEUTRAL | BUY | STRONG BUY | SELL | STRONG SELL
  confidence                text,                     -- LOW | MEDIUM | HIGH
  total_score               numeric,
  t0_close                  numeric,
  n_bars                    int,
  ret_1d                    numeric,
  ret_3d                    numeric,
  ret_5d                    numeric,
  ret_10d                   numeric,
  mfe_pct                   numeric,
  mae_pct                   numeric,
  schema_version            int,
  synced_at                 timestamptz not null default now(),
  unique (symbol, signal_date, snap_time, lens)
);

create index idx_v4_outcomes_sym_date on public.v4_outcomes (symbol, signal_date desc);
create index idx_v4_outcomes_pred     on public.v4_outcomes (pred_id);
create index idx_v4_outcomes_date     on public.v4_outcomes (signal_date desc);

-- RLS: đọc công khai (repo vốn public); ghi chỉ service_role (bypass RLS).
alter table public.v4_outcomes enable row level security;
create policy "read v4_outcomes" on public.v4_outcomes for select to anon, authenticated using (true);
