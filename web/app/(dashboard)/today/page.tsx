import { DataStatusPanel, type DataStatusItem, type DataStatusTone } from "@/components/data-status-panel";
import { PageHeader, EmptyState, QueryErrorState } from "@/components/ui";
import { TodayBoard, type TodayPriceStat, type TodaySignal } from "@/components/today-board";
import { getLatestVersionRuns } from "@/lib/dashboard-data";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { dateTimeVN, hmVN } from "@/lib/format";
import { TODAY_COMPARE_VERSIONS } from "@/lib/today-compare";
import { REVIEW_VERSIONS, type ReviewVersion } from "@/lib/scoring-versions";
import { servingForSource } from "@/lib/data-source/vnstock6-serving";
import { getDashboardDataSource } from "@/lib/data-source/source";

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
  const requestedSource = await getDashboardDataSource();
  const metadata = await getLatestVersionRuns("today-compare-metadata", requestedSource);
  if (metadata.error) {
    return <><PageHeader title="Hôm nay" desc={requestedSource === "vnstock6" ? "Tín hiệu native v6.2." : "Đối chiếu tín hiệu v4.17–v4.19."} /><QueryErrorState hint="Không đọc được metadata scoring version từ nguồn đã chọn." /></>;
  }

  const activeVersions: readonly ReviewVersion[] = metadata.source === "vnstock6"
    ? REVIEW_VERSIONS.filter((version) => version.startsWith("v6.") && metadata.byVersion[version])
    : TODAY_COMPARE_VERSIONS;
  const versionDates = Object.fromEntries(activeVersions.flatMap((version) => {
    const date = metadata.versionDates[version];
    return date ? [[version, date]] : [];
  })) as Record<string, string>;

  const signalResponses = await Promise.all(activeVersions.map(async (version) => {
    const signalDate = versionDates[version];
    if (!signalDate) return { version, data: [] as TodaySignal[], error: null };
    if (metadata.source !== "supabase") {
      try {
        const snapshot = await servingForSource(metadata.source).today(version);
        return { version, data: snapshot.signals as unknown as TodaySignal[], error: null };
      } catch (error) {
        return { version, data: [] as TodaySignal[], error };
      }
    }
    const client = createCachedPublicClient(`today-compare-${version}`, version);
    const response = await client.from("v4_signals").select(SIGNAL_COLUMNS)
      .eq("scoring_version", version).eq("signal_date", signalDate)
      .order("snap_time", { ascending: true });
    return { version, data: (response.data ?? []) as TodaySignal[], error: response.error };
  }));  const failed = signalResponses.find((response) => response.error);
  if (failed) {
    return <><PageHeader title="Hôm nay" desc={requestedSource === "vnstock6" ? "Tín hiệu native v6.2." : "Đối chiếu tín hiệu v4.17–v4.19."} /><QueryErrorState hint={`Không đọc được tín hiệu ${failed.version} từ nguồn đã chọn.`} /></>;
  }

  const signals = signalResponses.flatMap((response) => response.data);
  const baseClient = createCachedPublicClient("today-compare-health", "v4.18");

  // Pick one current price per symbol, from the newest dated snapshot across versions.
  // This avoids comparing an old version's price against a newer version's reference close.
  const latestPrices = new Map<string, { price: number; signalDate: string; snapTime: string; versionOrder: number; changePct: number | null }>();
  for (const signal of signals) {
    const price = signal.price == null || signal.price === "" ? NaN : Number(signal.price);
    if (!Number.isFinite(price) || price <= 0) continue;
    const versionOrder = activeVersions.indexOf(signal.scoring_version as ReviewVersion);
    if (versionOrder < 0) continue;
    const snapTime = signal.snap_time ?? "";
    const previous = latestPrices.get(signal.symbol);
    if (!previous || signal.signal_date > previous.signalDate ||
        (signal.signal_date === previous.signalDate &&
          (snapTime > previous.snapTime || (snapTime === previous.snapTime && versionOrder < previous.versionOrder)))) {
      const rawChange = (signal as TodaySignal & { changePct?: number | null }).changePct;
      const changePct = rawChange == null ? NaN : Number(rawChange);
      latestPrices.set(signal.symbol, {
        price,
        signalDate: signal.signal_date,
        snapTime,
        versionOrder,
        changePct: Number.isFinite(changePct) ? changePct : null,
      });
    }
  }

  const priceStats: Record<string, TodayPriceStat> = {};
  const symbolsByDate = new Map<string, string[]>();
  for (const [symbol, latest] of latestPrices) {
    priceStats[symbol] = { price: latest.price, changePct: metadata.source !== "supabase" ? latest.changePct : null };
    const symbols = symbolsByDate.get(latest.signalDate) ?? [];
    symbols.push(symbol);
    symbolsByDate.set(latest.signalDate, symbols);
  }

  // Follow the Buy tab: price change vs last trading session's OHLC close.
  // Query in small batches to stay below the Supabase 1,000-row response limit.
  const priceQueries = [...symbolsByDate.entries()].flatMap(([signalDate, symbols]) => {
    const start = new Date(`${signalDate}T00:00:00Z`);
    start.setUTCDate(start.getUTCDate() - 21);
    const since = start.toISOString().slice(0, 10);
    const batches: { signalDate: string; symbols: string[]; since: string }[] = [];
    for (let offset = 0; offset < symbols.length; offset += 40) {
      batches.push({ signalDate, symbols: symbols.slice(offset, offset + 40), since });
    }
    return batches;
  });
  const priceResponses = metadata.source !== "supabase" ? [] : await Promise.all(priceQueries.map(async (batch) => {
    const response = await baseClient.from("v4_ohlc").select("symbol, date, close")
      .in("symbol", batch.symbols).lt("date", batch.signalDate).gte("date", batch.since)
      .order("date", { ascending: false });
    return { batch, data: response.data, error: response.error };
  }));
  for (const response of priceResponses) {
    if (response.error) continue; // Missing OHLC must not break the entire Today page.
    const previousCloses = new Map<string, number>();
    for (const row of (response.data ?? []) as { symbol: string; close: number | string | null }[]) {
      const close = row.close == null ? NaN : Number(row.close);
      if (!previousCloses.has(row.symbol) && Number.isFinite(close) && close > 0) {
        previousCloses.set(row.symbol, close);
      }
    }
    for (const symbol of response.batch.symbols) {
      const previousClose = previousCloses.get(symbol);
      const current = priceStats[symbol];
      if (current && previousClose != null) {
        current.changePct = (current.price - previousClose) / previousClose * 100;
      }
    }
  }
  const { data: ohlc } = metadata.source !== "supabase"
    ? { data: null }
    : await baseClient.from("v4_ohlc").select("date, synced_at").order("date", { ascending: false }).limit(1).maybeSingle();
  const ohlcRow = ohlc as { date?: string; synced_at?: string } | null;
  const statusItems: DataStatusItem[] = [
    ...activeVersions.map((version) => {
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
  const latestTimes = activeVersions.flatMap((version) => {
    const run = metadata.byVersion[version];
    return run ? [`${version === "v4.19-shadow" ? "v4.19" : version} · ${versionDates[version]} · cập nhật ${hmVN(run.started_at)}`] : [];
  });

  return (
    <>
      <PageHeader title="Hôm nay" desc={`${symbolCount} mã hợp nhất · ${latestTimes.join(" · ")} (giờ VN)`} />
      <DataStatusPanel items={statusItems} />
      {signals.length ? <TodayBoard signals={signals} versions={activeVersions} versionDates={versionDates} priceStats={priceStats} /> : <EmptyState title="Chưa có dữ liệu cho nguồn đã chọn" hint="Cần ít nhất một run scoring hợp lệ cho nguồn đã chọn." />}
    </>
  );
}