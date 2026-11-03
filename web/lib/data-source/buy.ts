import type { BuySignal, ExpectancyRow, RobustnessRow } from "@/components/buy-board";
import { getCompanyName } from "@/lib/company-names";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { githubServing } from "./github-serving";
import type { DashboardDataSource } from "./source";

export interface BuyPageData {
  latestBuy: { run_id?: string; signal_date?: string; snap_time?: string } | null;
  newestRun: { run_id?: string } | null;
  signals: BuySignal[];
  runRow: { started_at?: string } | null;
  expectancy: ExpectancyRow[];
  robustness: RobustnessRow[];
  industryIC: Record<string, { ic: number | null; n: number }>;
}

async function loadSupabase(version: string): Promise<BuyPageData> {
  const db = createCachedPublicClient("buy", version);
  const latest = await db.from("v4_signals").select("run_id, signal_date, snap_time")
    .in("decision", ["BUY", "STRONG BUY"]).eq("scoring_version", version)
    .order("signal_date", { ascending: false }).order("snap_time", { ascending: false }).limit(1).maybeSingle();
  if (latest.error) throw latest.error;
  const latestBuy = latest.data as BuyPageData["latestBuy"];
  const industryBatch = await db.from("v4_ic_industry_batch").select("batch_id").eq("status", "ready").order("computed_at", { ascending: false }).limit(1).maybeSingle();
  const [newest, signalResponse, runResponse, exp, robust, industry] = await Promise.all([
    db.from("v4_runs").select("run_id").eq("scoring_version", version).order("started_at", { ascending: false }).limit(1).maybeSingle(),
    latestBuy?.run_id ? db.from("v4_signals").select("id, symbol, decision, score_trade, signal_date, breakdown")
      .eq("run_id", latestBuy.run_id).eq("scoring_version", version).in("decision", ["BUY", "STRONG BUY"]).order("score_trade", { ascending: false }) : Promise.resolve({ data: [], error: null }),
    latestBuy?.run_id ? db.from("v4_runs").select("started_at").eq("run_id", latestBuy.run_id).eq("scoring_version", version).maybeSingle() : Promise.resolve({ data: null, error: null }),
    db.from("v4_buy_expectancy").select("*").eq("scoring_version", version),
    db.from("v4_buy_robustness").select("*").eq("scoring_version", version),
    industryBatch.data ? db.from("v4_ic_industry_metrics").select("industry, ic, n").eq("batch_id", industryBatch.data.batch_id).eq("version", version).eq("factor", "score_trade").eq("horizon", 5) : Promise.resolve({ data: [], error: industryBatch.error }),
  ]);
  // Expectancy, robustness, industry IC and run metadata are enhancements.
  // Some public Supabase roles cannot read those views, so preserve the
  // original page behavior: only the core signals query is fatal.
  if (signalResponse.error) throw signalResponse.error;
  const signals = ((signalResponse.data ?? []) as BuySignal[]).map((row) => ({ ...row, companyName: getCompanyName(row.symbol) }));
  if (signals.length && latestBuy?.signal_date) {
    const since = new Date(new Date(latestBuy.signal_date).getTime() - 14 * 864e5).toISOString().slice(0, 10);
    const previous = await db.from("v4_ohlc").select("symbol, date, close")
      .in("symbol", signals.map((row) => row.symbol)).lt("date", latestBuy.signal_date).gte("date", since).order("date", { ascending: false });
    if (previous.error) throw previous.error;
    const closes = new Map<string, number>();
    for (const row of (previous.data ?? []) as { symbol: string; close: number }[]) if (!closes.has(row.symbol)) closes.set(row.symbol, Number(row.close));
    for (const signal of signals) {
      const price = Number((signal.breakdown ?? {}).price), close = closes.get(signal.symbol);
      signal.changePct = close && Number.isFinite(price) ? ((price - close) / close) * 100 : null;
    }
  }
  const industryIC: BuyPageData["industryIC"] = {};
  for (const row of (industry.data ?? []) as { industry: string; ic: number | string | null; n: number }[]) {
    industryIC[row.industry] = { ic: row.ic == null ? null : Number(row.ic), n: Number(row.n) };
  }
  return { latestBuy, newestRun: newest.data, signals, runRow: runResponse.data, expectancy: (exp.data ?? []) as ExpectancyRow[], robustness: (robust.data ?? []) as RobustnessRow[], industryIC };
}

async function loadGitHub(version: string): Promise<BuyPageData> {
  const data = await githubServing.buy(version);
  return {
    latestBuy: data.latestBuy as BuyPageData["latestBuy"], newestRun: data.newestRun as BuyPageData["newestRun"],
    signals: (data.signals as unknown as BuySignal[]).map((row) => ({ ...row, companyName: getCompanyName(row.symbol) })),
    runRow: data.runRow as BuyPageData["runRow"], expectancy: data.expectancy as unknown as ExpectancyRow[],
    robustness: data.robustness as unknown as RobustnessRow[], industryIC: data.industryIC,
  };
}

export async function getBuyPageData(version: string, source: DashboardDataSource): Promise<BuyPageData> {
  return source === "github" ? loadGitHub(version) : loadSupabase(version);
}
