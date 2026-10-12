import { PageHeader, EmptyState } from "@/components/ui";
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
const currentVersion = String(run.scoring_version || "v4.18");
  const requestedVersions = [...new Set([currentVersion, "v4.17"])];
  const versionResults = await Promise.all(requestedVersions.map(async (version) => {
    const { data: latest } = await supabase
      .from("v4_signals")
      .select("signal_date")
      .eq("scoring_version", version)
      .order("signal_date", { ascending: false })
      .limit(1)
      .maybeSingle();
    const signalDate = latest?.signal_date as string | undefined;
    if (!signalDate) return { version, signalDate: null, rows: [] as TodaySignal[] };
    const { data } = await supabase
      .from("v4_signals")
      .select("symbol, signal_date, scoring_version, decision, score_trade, snap_time, price:breakdown->>price, confidence:breakdown->>confidence, ff_intra_net:breakdown->>ff_intra_net, ff_intra_ratio:breakdown->>ff_intra_ratio, n_aligned:breakdown->>n_supergroups_aligned, ff_score:breakdown->>ff_score, fundamental_score:breakdown->>fundamental_score, entry:breakdown->>entry, stop:breakdown->>stop, tp1:breakdown->>tp1, breakdown")
      .eq("scoring_version", version)
      .eq("signal_date", signalDate)
      .order("score_trade", { ascending: false });
    return { version, signalDate, rows: (data ?? []) as TodaySignal[] };
  }));
  const signals = versionResults.flatMap((result) => result.rows);
  const versionDates = Object.fromEntries(versionResults.filter((result) => result.signalDate).map((result) => [result.version, result.signalDate!])) as Record<string, string>;
  const currentSignals = signals.filter((signal) => signal.scoring_version === currentVersion);
  const currentDate = versionDates[currentVersion] ?? String(run.run_id).split("_")[0];
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
