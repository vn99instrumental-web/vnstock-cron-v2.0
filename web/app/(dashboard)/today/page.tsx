import { DataStatusPanel, type DataStatusItem, type DataStatusTone } from "@/components/data-status-panel";
import { PageHeader, EmptyState, QueryErrorState } from "@/components/ui";
import { TodayBoard, type TodaySignal } from "@/components/today-board";
import { getLatestVersionRuns } from "@/lib/dashboard-data";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { dateTimeVN, hmVN } from "@/lib/format";
import { TODAY_COMPARE_VERSIONS } from "@/lib/today-compare";

export const dynamic = "force-dynamic";

function ageTone(timestamp: string | null | undefined, okHours: number, warnHours: number): DataStatusTone {
  if (!timestamp) return "unknown";
  const ageHours = (Date.now() - new Date(timestamp).getTime()) / 3_600_000;
  if (!Number.isFinite(ageHours)) return "unknown";
  return ageHours <= okHours ? "ok" : ageHours <= warnHours ? "warn" : "stale";
}

function dateAgeTone(dateValue: string | null | undefined, okDays: number, warnDays: number): DataStatusTone {
  if (!dateValue) return "unknown";
  const ageDays = (Date.now() - new Date(`${dateValue}T00:00:00+07:00`).getTime()) / 86_400_000;
  return ageDays <= okDays ? "ok" : ageDays <= warnDays ? "warn" : "stale";
}

const SIGNAL_COLUMNS = "symbol, signal_date, scoring_version, decision, score_trade, snap_time, price:breakdown->>price, confidence:breakdown->>confidence, ff_intra_net:breakdown->>ff_intra_net, ff_intra_ratio:breakdown->>ff_intra_ratio, n_aligned:breakdown->>n_supergroups_aligned, ff_score:breakdown->>ff_score, fundamental_score:breakdown->>fundamental_score, entry:breakdown->>entry, stop:breakdown->>stop, tp1:breakdown->>tp1, breakdown";

export default async function TodayPage() {
  const metadata = await getLatestVersionRuns("today-compare-metadata");
  if (metadata.error) {
    return <><PageHeader title="Hôm nay" desc="Đối chiếu tín hiệu v4.17–v4.19." /><QueryErrorState hint="Không đọc được metadata scoring version từ Supabase." /></>;
  }

  const versionDates = Object.fromEntries(TODAY_COMPARE_VERSIONS.flatMap((version) => {
    const date = metadata.versionDates[version];
    return date ? [[version, date]] : [];
  })) as Record<string, string>;

  const signalResponses = await Promise.all(TODAY_COMPARE_VERSIONS.map(async (version) => {
    const signalDate = versionDates[version];
    if (!signalDate) return { version, data: [] as TodaySignal[], error: null };
    const client = createCachedPublicClient(`today-compare-${version}`, version);
    const response = await client.from("v4_signals").select(SIGNAL_COLUMNS)
      .eq("scoring_version", version).eq("signal_date", signalDate)
      .order("snap_time", { ascending: true });
    return { version, data: (response.data ?? []) as TodaySignal[], error: response.error };
  }));
  const failed = signalResponses.find((response) => response.error);
  if (failed) {
    return <><PageHeader title="Hôm nay" desc="Đối chiếu tín hiệu v4.17–v4.19." /><QueryErrorState hint={`Không đọc được tín hiệu ${failed.version} từ Supabase.`} /></>;
  }

  const signals = signalResponses.flatMap((response) => response.data);
  const baseClient = createCachedPublicClient("today-compare-health", "v4.18");
  const { data: ohlc } = await baseClient.from("v4_ohlc").select("date, synced_at").order("date", { ascending: false }).limit(1).maybeSingle();
  const ohlcRow = ohlc as { date?: string; synced_at?: string } | null;
  const statusItems: DataStatusItem[] = [
    ...TODAY_COMPARE_VERSIONS.map((version) => {
      const run = metadata.byVersion[version];
      return {
        label: `Run ${version === "v4.19-shadow" ? "v4.19" : version}`,
        value: run ? dateTimeVN(run.started_at) : "—",
        detail: run?.run_id ?? "chưa có run",
        tone: ageTone(run?.started_at, 6, 30),
      } satisfies DataStatusItem;
    }),
    { label: "Giá OHLC", value: ohlcRow?.date ?? "—", detail: ohlcRow?.synced_at ? `sync ${dateTimeVN(ohlcRow.synced_at)}` : "chưa có thời điểm sync", tone: dateAgeTone(ohlcRow?.date, 3, 5) },
  ];

  const symbolCount = new Set(signals.map((signal) => signal.symbol)).size;
  const latestTimes = TODAY_COMPARE_VERSIONS.flatMap((version) => {
    const run = metadata.byVersion[version];
    return run ? [`${version === "v4.19-shadow" ? "v4.19" : version} · ${versionDates[version]} · cập nhật ${hmVN(run.started_at)}`] : [];
  });

  return (
    <>
      <PageHeader title="Hôm nay" desc={`${symbolCount} mã hợp nhất · ${latestTimes.join(" · ")} (giờ VN)`} />
      <DataStatusPanel items={statusItems} />
      {signals.length ? <TodayBoard signals={signals} versionDates={versionDates} /> : <EmptyState title="Chưa có dữ liệu cho ba version" hint="Cần ít nhất một run v4.17, v4.18 hoặc v4.19." />}
    </>
  );
}