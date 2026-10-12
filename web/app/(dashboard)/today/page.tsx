import { PageHeader, EmptyState } from "@/components/ui";
import { TodayBoard, type TodaySignal } from "@/components/today-board";
import { createClient } from "@/lib/supabase/server";
import { hmVN } from "@/lib/format";

export const dynamic = "force-dynamic";

type TodayPageProps = { searchParams: Promise<{ version?: string }> };

export default async function TodayPage({ searchParams }: TodayPageProps) {
  const params = await searchParams;
  const supabase = await createClient();

  // Run mới nhất = (signal_date, snap_time) lớn nhất → started_at desc.
  const { data: run } = await supabase
    .from("v4_runs")
    .select("run_id, started_at, scoring_version, gate_version, universe_size, n_buy, health")
    .eq("scoring_version", "v4.18")
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
  const productionVersion = "v4.18";
  const { data: recentRuns } = await supabase
    .from("v4_runs")
    .select("run_id, started_at, scoring_version")
    .not("scoring_version", "is", null)
    .order("started_at", { ascending: false })
    .limit(1000);
  const versionDates: Record<string, string> = {};
  for (const item of recentRuns ?? []) {
    const version = String(item.scoring_version);
    if (!versionDates[version]) versionDates[version] = String(item.run_id).split("_")[0];
  }
  versionDates[productionVersion] ??= String(run.run_id).split("_")[0];
  const requestedVersion = typeof params.version === "string" ? params.version : productionVersion;
  const currentVersion = versionDates[requestedVersion] ? requestedVersion : productionVersion;
  const currentDate = versionDates[currentVersion];
  const { data } = await supabase
    .from("v4_signals")
    .select("symbol, signal_date, scoring_version, decision, score_trade, snap_time, price:breakdown->>price, confidence:breakdown->>confidence, ff_intra_net:breakdown->>ff_intra_net, ff_intra_ratio:breakdown->>ff_intra_ratio, n_aligned:breakdown->>n_supergroups_aligned, ff_score:breakdown->>ff_score, fundamental_score:breakdown->>fundamental_score, entry:breakdown->>entry, stop:breakdown->>stop, tp1:breakdown->>tp1, breakdown")
    .eq("scoring_version", currentVersion)
    .eq("signal_date", currentDate)
    .order("score_trade", { ascending: false });
  const signals = (data ?? []) as TodaySignal[];
  const currentSignals = signals;
  const totalSnaps = new Set(currentSignals.map((signal) => String(signal.snap_time))).size;
  const nSymbols = new Set(currentSignals.map((signal) => signal.symbol)).size;
  return (
    <>
      <PageHeader
        title="Hôm nay"
        desc={`${currentDate} · ${totalSnaps} lần chạy · ${nSymbols} mã · phiên mới nhất ${hmVN(run.started_at)} (giờ VN)`}
      />
      {signals.length ? (
        <TodayBoard signals={signals} currentVersion={currentVersion} versionDates={versionDates} />
      ) : (
        <EmptyState title="Phiên này chưa có tín hiệu" />
      )}
    </>
  );
}
