import { PageHeader, EmptyState, Card } from "@/components/ui";
import { TodayBoard, type TodaySignal } from "@/components/today-board";
import { createClient } from "@/lib/supabase/server";
import { hmVN } from "@/lib/format";

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
        <PageHeader title="Hôm nay" desc="Tín hiệu của phiên mới nhất." />
        <EmptyState
          title="Chưa có dữ liệu tín hiệu"
          hint="Bảng v4_signals đang rỗng — chờ sync (E1) chạy trên GitHub Actions."
        />
      </>
    );
  }

  // Ngày của run mới nhất (prefix run_id "YYYY-MM-DD_HH:MM"). Lấy TẤT CẢ snap trong ngày
  // → gộp theo mã (1 mã có thể BUY nhiều lần chạy).
  const theDate = String(run.run_id).split("_")[0];
  const { data: sigs } = await supabase
    .from("v4_signals")
    .select("symbol, decision, score_trade, snap_time, price:breakdown->>price, confidence:breakdown->>confidence, ff_intra_net:breakdown->>ff_intra_net, ff_intra_ratio:breakdown->>ff_intra_ratio, n_aligned:breakdown->>n_supergroups_aligned, ff_score:breakdown->>ff_score, fundamental_score:breakdown->>fundamental_score")
    .eq("signal_date", theDate)
    .order("score_trade", { ascending: false });

  const signals = (sigs ?? []) as TodaySignal[];
  const totalSnaps = new Set(signals.map((s) => String(s.snap_time))).size;
  const nSymbols = new Set(signals.map((s) => s.symbol)).size;

  return (
    <>
      <PageHeader
        title="Hôm nay"
        desc={`${theDate} · ${totalSnaps} lần chạy · ${nSymbols} mã · phiên mới nhất ${hmVN(run.started_at)} (giờ VN)`}
      />
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Số mã" value={String(nSymbols)} />
        <Stat label="BUY (phiên mới nhất)" value={String(run.n_buy ?? "—")} />
        <Stat label="Regime" value={String(run.health?.regime ?? "—")} />
        <Stat label="Scoring" value={String(run.scoring_version ?? "—")} mono />
      </div>
      {signals.length ? (
        <TodayBoard signals={signals} totalSnaps={totalSnaps} />
      ) : (
        <EmptyState title="Phiên này chưa có tín hiệu" />
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
