import { DataStatusPanel, type DataStatusItem, type DataStatusTone } from "@/components/data-status-panel";
import { PageHeader, EmptyState, QueryErrorState } from "@/components/ui";
import { TodayBoard, type TodaySignal } from "@/components/today-board";
import { getLatestVersionRuns, resolveReviewVersion } from "@/lib/dashboard-data";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { dateTimeVN, hmVN } from "@/lib/format";

export const dynamic = "force-dynamic";

type TodayPageProps = { searchParams: Promise<{ version?: string }> };

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

export default async function TodayPage({ searchParams }: TodayPageProps) {
  const params = await searchParams;
  const metadata = await getLatestVersionRuns();
  const currentVersion = resolveReviewVersion(params.version, metadata.byVersion);
  const run = metadata.byVersion[currentVersion];
  const versionDates = Object.fromEntries(Object.entries(metadata.versionDates).filter(([, value]) => !!value)) as Record<string, string>;

  if (metadata.error) {
    return <><PageHeader title="Hôm nay" desc="Tín hiệu của phiên mới nhất." /><QueryErrorState hint="Không đọc được metadata các scoring version từ Supabase." /></>;
  }
  if (!run) {
    return <><PageHeader title="Hôm nay" desc="Tín hiệu của phiên mới nhất." /><EmptyState title="Chưa có dữ liệu tín hiệu" hint="Chưa có run cho scoring version đã chọn." /></>;
  }

  const currentDate = versionDates[currentVersion];
  const dataClient = createCachedPublicClient("today", currentVersion);
  const [signalsResult, ohlcResult, outcomeResult, icResult] = await Promise.all([
    dataClient
      .from("v4_signals")
      .select("symbol, signal_date, scoring_version, decision, score_trade, snap_time, price:breakdown->>price, confidence:breakdown->>confidence, ff_intra_net:breakdown->>ff_intra_net, ff_intra_ratio:breakdown->>ff_intra_ratio, n_aligned:breakdown->>n_supergroups_aligned, ff_score:breakdown->>ff_score, fundamental_score:breakdown->>fundamental_score, entry:breakdown->>entry, stop:breakdown->>stop, tp1:breakdown->>tp1, breakdown")
      .eq("scoring_version", currentVersion)
      .eq("signal_date", currentDate)
      .order("score_trade", { ascending: false }),
    dataClient.from("v4_ohlc").select("date, synced_at").order("date", { ascending: false }).limit(1).maybeSingle(),
    dataClient.from("v4_outcomes").select("signal_date, eval_date, synced_at").eq("scoring_version", currentVersion).order("eval_date", { ascending: false }).limit(1).maybeSingle(),
    dataClient.from("v4_ic_metrics").select("computed_at").eq("config_version", currentVersion).order("computed_at", { ascending: false }).limit(1).maybeSingle(),
  ]);

  if (signalsResult.error) {
    return <><PageHeader title="Hôm nay" desc={`${currentVersion} · ${currentDate}`} /><QueryErrorState hint="Supabase không trả được danh sách tín hiệu của phiên đã chọn." /></>;
  }

  const signals = (signalsResult.data ?? []) as TodaySignal[];
  const totalSnaps = new Set(signals.map((signal) => String(signal.snap_time))).size;
  const nSymbols = new Set(signals.map((signal) => signal.symbol)).size;
  const ohlc = ohlcResult.data as { date?: string; synced_at?: string } | null;
  const outcome = outcomeResult.data as { signal_date?: string; eval_date?: string; synced_at?: string } | null;
  const ic = icResult.data as { computed_at?: string } | null;
  const statusItems: DataStatusItem[] = [
    { label: `Run ${currentVersion}`, value: dateTimeVN(run.started_at), detail: run.run_id, tone: ageTone(run.started_at, 6, 30) },
    { label: "Giá OHLC", value: ohlc?.date ?? "—", detail: ohlc?.synced_at ? `sync ${dateTimeVN(ohlc.synced_at)}` : "chưa có thời điểm sync", tone: dateAgeTone(ohlc?.date, 3, 5) },
    { label: "Outcome đã chín", value: outcome?.eval_date ?? "—", detail: outcome?.signal_date ? `tín hiệu đến ${outcome.signal_date}` : "chưa có outcome", tone: dateAgeTone(outcome?.eval_date, 3, 7) },
    { label: "IC", value: ic?.computed_at ? dateTimeVN(ic.computed_at) : "—", detail: `scoring ${currentVersion}`, tone: ageTone(ic?.computed_at, 36, 72) },
  ];

  return (
    <>
      <PageHeader title="Hôm nay" desc={`${currentDate} · ${totalSnaps} lần chạy · ${nSymbols} mã · phiên mới nhất ${hmVN(run.started_at)} (giờ VN)`} />
      <DataStatusPanel items={statusItems} />
      {signals.length ? <TodayBoard signals={signals} currentVersion={currentVersion} versionDates={versionDates} /> : <EmptyState title="Phiên này chưa có tín hiệu" />}
    </>
  );
}
