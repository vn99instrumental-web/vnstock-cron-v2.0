import { PageHeader, EmptyState, Card } from "@/components/ui";
import { SignalsTable, type SignalRow } from "@/components/signals-table";
import { createClient } from "@/lib/supabase/server";
import { snapHM } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const supabase = await createClient();

  // Run mới nhất = (signal_date, snap_time) lớn nhất → started_at desc.
  const { data: run } = await supabase
    .from("v4_runs")
    .select("run_id, started_at, scoring_version, gate_version, universe_size, n_buy, health")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (!run) {
    return (
      <>
        <PageHeader title="Hôm nay" desc="Tín hiệu của run mới nhất." />
        <EmptyState
          title="Chưa có dữ liệu tín hiệu"
          hint="Bảng v4_signals đang rỗng — chờ sync (E1) chạy trên GitHub Actions."
        />
      </>
    );
  }

  const { data: signals } = await supabase
    .from("v4_signals")
    .select("id, symbol, decision, score_trade, regime, signal_date, snap_time, scoring_version, breakdown")
    .eq("run_id", run.run_id)
    .order("score_trade", { ascending: false });

  const rows = (signals ?? []) as SignalRow[];

  return (
    <>
      <PageHeader
        title="Hôm nay"
        desc={`Run ${run.run_id} · ${snapHM(run.started_at)} · ${run.universe_size ?? rows.length} mã`}
      />
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Số tín hiệu" value={String(rows.length)} />
        <Stat label="BUY / STRONG BUY" value={String(run.n_buy ?? "—")} />
        <Stat label="Regime" value={String(run.health?.regime ?? "—")} />
        <Stat label="Scoring" value={String(run.scoring_version ?? "—")} mono />
      </div>
      {rows.length ? (
        <SignalsTable rows={rows} />
      ) : (
        <EmptyState title="Run này chưa có tín hiệu" />
      )}
    </>
  );
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <Card>
      <div className="text-xs text-[var(--color-muted)]">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${mono ? "font-mono" : ""}`}>{value}</div>
    </Card>
  );
}
