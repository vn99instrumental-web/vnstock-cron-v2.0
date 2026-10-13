import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import {
  DEFAULT_SCORING_VERSION,
  REVIEW_VERSIONS,
  isReviewVersion,
  type ReviewVersion,
} from "@/lib/scoring-versions";

export interface LatestVersionRun {
  run_id: string;
  started_at: string;
  scoring_version: ReviewVersion;
  gate_version: string | null;
  universe_size: number | null;
  n_buy: number | null;
  health: unknown;
}

/** Fetch one latest row per curated version instead of downloading up to 1,000 runs. */
export async function getLatestVersionRuns(scope = "version-metadata") {
  const client = createCachedPublicClient(scope, DEFAULT_SCORING_VERSION);
  const results = await Promise.all(
    REVIEW_VERSIONS.map(async (version) => {
      const response = await client
        .from("v4_runs")
        .select("run_id, started_at, scoring_version, gate_version, universe_size, n_buy, health")
        .eq("scoring_version", version)
        .order("started_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      return { version, ...response };
    }),
  );

  const error = results.find((item) => item.error)?.error ?? null;
  const runs: LatestVersionRun[] = [];
  for (const item of results) {
    const row = item.data;
    if (row && isReviewVersion(row.scoring_version)) {
      runs.push({ ...row, scoring_version: row.scoring_version } as LatestVersionRun);
    }
  }
  const versionDates: Partial<Record<ReviewVersion, string>> = {};
  const byVersion: Partial<Record<ReviewVersion, LatestVersionRun>> = {};
  for (const run of runs) {
    byVersion[run.scoring_version] = run;
    versionDates[run.scoring_version] = String(run.run_id).split("_")[0];
  }
  return { runs, byVersion, versionDates, error };
}

export function resolveReviewVersion(
  requested: unknown,
  available: Partial<Record<ReviewVersion, unknown>>,
): ReviewVersion {
  return isReviewVersion(requested) && available[requested]
    ? requested
    : DEFAULT_SCORING_VERSION;
}