-- Keep the legacy result view on the querying role's RLS boundary.
alter view public.v4_signal_results set (security_invoker = true);

revoke all on public.v4_signal_results from anon, authenticated;
grant select on public.v4_signal_results to anon, authenticated;
