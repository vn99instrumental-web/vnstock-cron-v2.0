const ACTIVE_TTL_SECONDS = 5 * 60;

function baseUrl(): string {
  return (process.env.GITHUB_SERVING_BASE_URL
    ?? "https://raw.githubusercontent.com/vn99instrumental-web/vnstock-cron-v2.0/main/output/serving/current")
    .replace(/\/+$/, "");
}

function safeSegment(value: string): string {
  if (!/^[A-Za-z0-9._-]+$/.test(value)) throw new Error("Invalid GitHub serving path segment");
  return value;
}

export async function fetchGitHubServing<T>(path: string): Promise<T> {
  const cleanPath = path.split("/").map(safeSegment).join("/");
  const response = await fetch(`${baseUrl()}/${cleanPath}`, {
    cache: "force-cache",
    next: {
      revalidate: ACTIVE_TTL_SECONDS,
      tags: ["dashboard-data", "github-serving", `github-serving-${cleanPath.split("/")[0]}`],
    },
  });
  if (!response.ok) throw new Error(`GitHub serving ${cleanPath} returned HTTP ${response.status}`);
  return await response.json() as T;
}

export interface GitHubMetadata {
  schema_version: 1;
  release_id: string;
  generated_at: string;
  runs: Record<string, {
    run_id: string;
    started_at: string;
    scoring_version: string;
    gate_version: string | null;
    universe_size: number | null;
    n_buy: number | null;
    health: unknown;
  }>;
}

export interface GitHubTodaySnapshot {
  version: string;
  signal_date: string;
  run: GitHubMetadata["runs"][string];
  signals: Array<Record<string, unknown>>;
  status: {
    ohlc: Record<string, unknown> | null;
    outcome: Record<string, unknown> | null;
    ic: Record<string, unknown> | null;
  };
}

export interface GitHubBuySnapshot {
  version: string;
  latestBuy: Record<string, unknown> | null;
  newestRun: Record<string, unknown> | null;
  signals: Array<Record<string, unknown>>;
  runRow: Record<string, unknown> | null;
  expectancy: Array<Record<string, unknown>>;
  robustness: Array<Record<string, unknown>>;
  industryIC: Record<string, { ic: number | null; n: number }>;
}

export interface GitHubAnalysisSnapshot {
  version: string;
  results: Array<Record<string, unknown>>;
  corr: Array<Record<string, unknown>>;
  pairs: Array<Record<string, unknown>>;
  split: Array<Record<string, unknown>>;
}

export interface GitHubHistorySnapshot {
  version: string;
  rows: Array<Record<string, unknown>>;
  count: number;
}

export interface GitHubChartSnapshot {
  ohlc: Array<Record<string, unknown>>;
  signals: Array<Record<string, unknown>>;
}

export const githubServing = {
  metadata: () => fetchGitHubServing<GitHubMetadata>("metadata.json"),
  today: (version: string) => fetchGitHubServing<GitHubTodaySnapshot>(`today/${safeSegment(version)}.json`),
  buy: (version: string) => fetchGitHubServing<GitHubBuySnapshot>(`buy/${safeSegment(version)}.json`),
  analysis: (version: string) => fetchGitHubServing<GitHubAnalysisSnapshot>(`analysis/${safeSegment(version)}.json`),
  history: (version: string) => fetchGitHubServing<GitHubHistorySnapshot>(`history/${safeSegment(version)}.json`),
  chart: (version: string, symbol: string) => fetchGitHubServing<GitHubChartSnapshot>(
    `charts/${safeSegment(version)}/${safeSegment(symbol.toUpperCase())}.json`,
  ),
};
