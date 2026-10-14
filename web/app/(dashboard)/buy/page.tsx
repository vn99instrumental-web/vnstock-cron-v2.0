import { PageHeader } from "@/components/ui";
import { BuyBoard, type BuySignal, type ExpectancyRow, type RobustnessRow } from "@/components/buy-board";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { getCompanyName } from "@/lib/company-names";
import { getLatestVersionRuns, resolveReviewVersion } from "@/lib/dashboard-data";

export const dynamic = "force-dynamic";

type BuyPageProps = { searchParams: Promise<{ version?: string }> };

export default async function BuyPage({ searchParams }: BuyPageProps) {
  const params = await searchParams;
  const metadata = await getLatestVersionRuns("buy-metadata");
  const currentVersion = resolveReviewVersion(params.version, metadata.byVersion);
  const versionDates = Object.fromEntries(Object.entries(metadata.versionDates).filter(([, value]) => !!value)) as Record<string, string>;
  const dataClient = createCachedPublicClient("buy", currentVersion);

  const [latestBuyResponse, newestRunResponse] = await Promise.all([
    dataClient.from("v4_signals").select("run_id, signal_date, snap_time")
      .in("decision", ["BUY", "STRONG BUY"]).eq("scoring_version", currentVersion)
      .order("signal_date", { ascending: false }).order("snap_time", { ascending: false }).limit(1).maybeSingle(),
    dataClient.from("v4_runs").select("run_id").eq("scoring_version", currentVersion)
      .order("started_at", { ascending: false }).limit(1).maybeSingle(),
  ]);
  if (metadata.error || latestBuyResponse.error) throw metadata.error ?? latestBuyResponse.error;
  const latestBuy = latestBuyResponse.data;
  const newestRun = newestRunResponse.data;

  const [signalsResponse, runResponse, expectancyResponse, robustnessResponse, industryResponse] = await Promise.all([
    latestBuy
      ? dataClient.from("v4_signals").select("id, symbol, decision, score_trade, signal_date, breakdown")
          .eq("run_id", latestBuy.run_id).eq("scoring_version", currentVersion)
          .in("decision", ["BUY", "STRONG BUY"]).order("score_trade", { ascending: false })
      : Promise.resolve({ data: [], error: null }),
    latestBuy
      ? dataClient.from("v4_runs").select("started_at").eq("run_id", latestBuy.run_id)
          .eq("scoring_version", currentVersion).maybeSingle()
      : Promise.resolve({ data: null, error: null }),
    dataClient.from("v4_buy_expectancy").select("*").eq("scoring_version", currentVersion),
    dataClient.from("v4_buy_robustness").select("*").eq("scoring_version", currentVersion),
    dataClient.from("v4_ic_by_industry_ver").select("industry, ic, n")
      .eq("version", currentVersion).eq("horizon", 5),
  ]);

  if (signalsResponse.error) throw signalsResponse.error;
  const signals = ((signalsResponse.data ?? []) as BuySignal[]).map((signal) => ({
    ...signal,
    companyName: getCompanyName(signal.symbol),
  }));

  if (signals.length && latestBuy) {
    const sigDate = latestBuy.signal_date as string;
    const since = new Date(new Date(sigDate).getTime() - 14 * 864e5).toISOString().slice(0, 10);
    const { data: ohlc } = await dataClient.from("v4_ohlc").select("symbol, date, close")
      .in("symbol", signals.map((signal) => signal.symbol)).lt("date", sigDate).gte("date", since)
      .order("date", { ascending: false });
    const previousClose = new Map<string, number>();
    for (const row of (ohlc ?? []) as { symbol: string; close: number }[]) {
      if (!previousClose.has(row.symbol)) previousClose.set(row.symbol, Number(row.close));
    }
    for (const signal of signals) {
      const price = Number((signal.breakdown ?? {}).price);
      const previous = previousClose.get(signal.symbol);
      signal.changePct = previous && Number.isFinite(price) ? (price - previous) / previous * 100 : null;
    }
  }

  const runRow = runResponse.data as { started_at?: string } | null;
  const startedAt = runRow?.started_at ?? null;
  let freshText = "";
  if (startedAt && latestBuy) {
    const minutes = Math.max(0, Math.round((Date.now() - new Date(startedAt).getTime()) / 60000));
    const ago = minutes < 1 ? "vừa xong" : minutes < 60 ? `${minutes} phút trước` : (() => {
      const hours = Math.floor(minutes / 60);
      return hours < 24 ? `${hours} giờ trước` : `${Math.floor(hours / 24)} ngày trước`;
    })();
    const vietnamNow = new Date(Date.now() + 7 * 3600e3);
    const day = vietnamNow.getUTCDay();
    const hour = vietnamNow.getUTCHours() + vietnamNow.getUTCMinutes() / 60;
    const marketOpen = day >= 1 && day <= 5 && hour >= 9 && hour <= 15;
    freshText = ` · Run ${latestBuy.run_id} · cập nhật ${ago} · ${marketOpen ? "phiên ĐANG MỞ" : "ngoài phiên"}`;
  }

  const industryIC: Record<string, { ic: number | null; n: number }> = {};
  for (const row of (industryResponse.data ?? []) as { industry: string; ic: number | string | null; n: number }[]) {
    industryIC[row.industry] = { ic: row.ic == null ? null : Number(row.ic), n: Number(row.n) };
  }

  return (
    <>
      <PageHeader title="Mua" desc={`${currentVersion} · ${signals.length} mã BUY / STRONG BUY${freshText}`} />
      <BuyBoard
        signals={signals}
        expectancy={(expectancyResponse.data ?? []) as ExpectancyRow[]}
        robustness={(robustnessResponse.data ?? []) as RobustnessRow[]}
        runId={latestBuy?.run_id}
        runStartedAt={startedAt}
        newestRunId={(newestRun?.run_id as string | undefined) ?? null}
        industryIC={industryIC}
        currentVersion={currentVersion}
        versionDates={versionDates}
      />
    </>
  );
}
