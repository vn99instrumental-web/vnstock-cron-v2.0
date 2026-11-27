import {
  fetchGitHubLedgerText,
  type GitHubAnalysisSnapshot,
  type GitHubBuySnapshot,
  type GitHubChartSnapshot,
  type GitHubHistorySnapshot,
  type GitHubMetadata,
  type GitHubTodaySnapshot,
} from "@/lib/data-source/github-serving";
import { getSsiIndependentDashboard, type SsiHistoryRow, type SsiLatestRow } from "@/lib/ssi-independent";

export const SSI_SCORING_VERSION = "ssi-v4.18-independent";
export const SSI_HISTORY_FALLBACK_VERSION = "v6.4.18";

async function dashboard() {
  const value = await getSsiIndependentDashboard();
  if (!value) throw new Error("SSI independent dashboard failed source/schema validation");
  return value;
}

function run(data: Awaited<ReturnType<typeof dashboard>>) {
  return {
    run_id: `${data.signal_date}_1530_${SSI_SCORING_VERSION}`,
    started_at: data.generated_at,
    scoring_version: SSI_SCORING_VERSION,
    gate_version: "ssi-independent",
    universe_size: data.summary.symbols,
    n_buy: data.summary.buy,
    health: {
      source: "SSI/FHSC",
      independent_calculation: true,
      minimum_signal_coverage: data.summary.minimum_signal_coverage,
    },
  };
}

function breakdown(row: SsiLatestRow): Record<string, unknown> {
  const signalFields = Object.fromEntries(Object.entries(row.signals).map(([key, value]) => [`s_${key}`, value]));
  const tradeFactors = Object.fromEntries(Object.entries(row.factors).map(([key, value]) => [`trade_${key}_norm`, value]));
  return {
    ...row,
    ...signalFields,
    ...tradeFactors,
    total_score: row.score_trade,
    score_hold: row.score_hold,
    missing_data_policy: "exclude_and_renormalize",
    excluded_factors: row.missing_signals,
    calculation_engine: "ssi_independent_python",
    calculation_version: "1.0.0",
    proprietary_flow_status: row.signals.prop_5d == null ? "not_available" : "available",
    insider_deal_status: row.signals.insider == null ? "not_available" : "available",
    depth_status: row.signals.depth_wall == null ? "missing_order_book" : "available",
  };
}

function todaySignal(row: SsiLatestRow): Record<string, unknown> {
  const detail = breakdown(row);
  return {
    symbol: row.symbol,
    scoring_version: SSI_SCORING_VERSION,
    pipeline_generation: "SSI_INDEPENDENT_1",
    market_source: "SSI",
    signal_date: row.signal_date,
    decision: row.decision,
    score_trade: row.score_trade,
    snap_time: row.snap_time,
    price: row.price,
    confidence: row.confidence,
    ff_intra_net: null,
    ff_intra_ratio: null,
    n_aligned: null,
    ff_score: row.signals.ff_net,
    fundamental_score: row.signals.fund_core,
    entry: row.price,
    stop: null,
    tp1: null,
    previous_close: null,
    changePct: null,
    breakdown: detail,
  };
}

function historyBreakdown(row: SsiHistoryRow): Record<string, unknown> {
  return {
    pred_id: row.pred_id,
    price: row.price,
    confidence: row.confidence,
    signal_coverage: row.signal_coverage,
    calculation_engine: "ssi_independent_python",
    display_source: "ssi_native",
    is_ssi_native: true,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function rowKey(row: Record<string, unknown>): string | null {
  const symbol = typeof row.symbol === "string" ? row.symbol.toUpperCase() : "";
  const signalDate = typeof row.signal_date === "string" ? row.signal_date : "";
  return /^[A-Z0-9]{2,12}$/.test(symbol) && /^\d{4}-\d{2}-\d{2}$/.test(signalDate)
    ? `${signalDate}|${symbol}`
    : null;
}

async function gen6HistoryFallback(nativeKeys: Set<string>): Promise<Array<Record<string, unknown>>> {
  try {
    const text = await fetchGitHubLedgerText(
      `output/serving/vnstock6/current/history/${SSI_HISTORY_FALLBACK_VERSION}.json`,
    );
    const payload: unknown = JSON.parse(text);
    if (!isRecord(payload) || !Array.isArray(payload.rows)) return [];

    const latestBySymbolDate = new Map<string, Record<string, unknown>>();
    for (const candidate of payload.rows) {
      if (!isRecord(candidate)) continue;
      const key = rowKey(candidate);
      if (!key || nativeKeys.has(key)) continue;
      const previous = latestBySymbolDate.get(key);
      const candidateTime = String(candidate.snap_time ?? "");
      const previousTime = String(previous?.snap_time ?? "");
      if (!previous || candidateTime >= previousTime) latestBySymbolDate.set(key, candidate);
    }

    return [...latestBySymbolDate.values()].map((row) => {
      const sourceBreakdown = isRecord(row.breakdown) ? row.breakdown : {};
      const fallbackId = row.id ?? `6|${row.symbol}|${row.signal_date}|${row.snap_time ?? "close"}|${SSI_HISTORY_FALLBACK_VERSION}`;
      return {
        ...row,
        id: fallbackId,
        scoring_version: SSI_HISTORY_FALLBACK_VERSION,
        breakdown: {
          ...sourceBreakdown,
          pred_id: sourceBreakdown.pred_id ?? fallbackId,
          display_source: "gen6_fallback",
          calculation_engine: "gen6",
          calculation_version: SSI_HISTORY_FALLBACK_VERSION,
          is_ssi_native: false,
        },
      };
    });
  } catch {
    // SSI-native history remains available when the optional Gen 6 history source is unavailable.
    return [];
  }
}

export const ssiServing = {
  async metadata(): Promise<GitHubMetadata> {
    const data = await dashboard();
    const currentRun = run(data);
    const dates = data.history.map((row) => row.signal_date).filter(Boolean).sort();
    return {
      schema_version: 2,
      release_id: `ssi-${data.generated_at}`,
      generated_at: data.generated_at,
      runs: { [SSI_SCORING_VERSION]: currentRun },
      coverage: {
        [SSI_SCORING_VERSION]: { min: dates[0] ?? data.signal_date, max: dates.at(-1) ?? data.signal_date },
      },
    };
  },
  async today(version: string): Promise<GitHubTodaySnapshot> {
    if (version !== SSI_SCORING_VERSION) throw new Error("Unsupported SSI scoring version");
    const data = await dashboard();
    return {
      version,
      signal_date: data.signal_date,
      run: run(data),
      signals: data.latest.map(todaySignal),
      status: { ohlc: null, outcome: null, ic: null },
    };
  },
  async buy(version: string): Promise<GitHubBuySnapshot> {
    if (version !== SSI_SCORING_VERSION) throw new Error("Unsupported SSI scoring version");
    const data = await dashboard();
    const selected = data.latest.filter((row) => row.decision === "BUY" || row.decision === "STRONG BUY");
    const currentRun = run(data);
    return {
      version,
      latestBuy: selected.length ? { run_id: currentRun.run_id, signal_date: data.signal_date, snap_time: selected[0].snap_time } : null,
      newestRun: { run_id: currentRun.run_id },
      signals: selected.map((row) => ({
        id: row.pred_id,
        symbol: row.symbol,
        decision: row.decision,
        score_trade: row.score_trade,
        signal_date: row.signal_date,
        breakdown: breakdown(row),
        changePct: null,
      })),
      runRow: { started_at: data.generated_at },
      expectancy: [],
      robustness: [],
      industryIC: {},
    };
  },
  async history(version: string): Promise<GitHubHistorySnapshot> {
    if (version !== SSI_SCORING_VERSION) throw new Error("Unsupported SSI scoring version");
    const data = await dashboard();
    const nativeRows: Array<Record<string, unknown>> = data.history.map((row) => ({
      id: row.pred_id,
      symbol: row.symbol,
      decision: row.decision,
      score_trade: row.score_trade,
      regime: null,
      signal_date: row.signal_date,
      snap_time: row.snap_time,
      scoring_version: version,
      breakdown: historyBreakdown(row),
      outcome: {
        pred_id: row.pred_id,
        ret_3d: row.ret_3d,
        ret_5d: row.ret_5d,
        ret_10d: row.ret_10d,
        mfe_pct: null,
        mae_pct: null,
      },
    }));
    const nativeKeys = new Set(nativeRows.flatMap((row) => {
      const key = rowKey(row);
      return key ? [key] : [];
    }));
    const fallbackRows = await gen6HistoryFallback(nativeKeys);
    const rows = [...nativeRows, ...fallbackRows].sort((left, right) => {
      const leftKey = `${String(left.signal_date ?? "")}|${String(left.snap_time ?? "")}`;
      const rightKey = `${String(right.signal_date ?? "")}|${String(right.snap_time ?? "")}`;
      return rightKey.localeCompare(leftKey);
    });
    return {
      version,
      rows,
      count: rows.length,
      source_counts: { ssi_native: nativeRows.length, gen6_fallback: fallbackRows.length },
    };
  },
  async analysis(version: string): Promise<GitHubAnalysisSnapshot> {
    if (version !== SSI_SCORING_VERSION) throw new Error("Unsupported SSI scoring version");
    const data = await dashboard();
    const results = data.history
      .filter((row) => row.decision === "BUY" || row.decision === "STRONG BUY")
      .map((row) => ({
        pred_id: row.pred_id,
        scoring_version: version,
        symbol: row.symbol,
        signal_date: row.signal_date,
        snap_time: row.snap_time,
        decision: row.decision,
        score_trade: row.score_trade,
        confidence: row.confidence,
        t0_close: row.price,
        ret_1d: null,
        ret_3d: row.ret_3d,
        ret_5d: row.ret_5d,
        ret_10d: row.ret_10d,
        mfe_pct: null,
        mae_pct: null,
        own_entry: row.price,
        own_tp1: null,
        own_tp2: null,
        own_stop: null,
        std_outcome: null,
        std_days: null,
        std3_outcome: null,
        own_outcome: null,
        own_days: null,
      }));
    return { version, results, corr: [], pairs: [], split: [] };
  },
  async chart(version: string, symbol: string): Promise<GitHubChartSnapshot> {
    if (version !== SSI_SCORING_VERSION) throw new Error("Unsupported SSI scoring version");
    const normalized = symbol.toUpperCase();
    const data = await dashboard();
    const signals = data.history.filter((row) => row.symbol === normalized).map((row) => ({
      signal_date: row.signal_date,
      snap_time: row.snap_time,
      decision: row.decision,
      price: row.price,
    }));
    return { ohlc: [], signals };
  },
};
