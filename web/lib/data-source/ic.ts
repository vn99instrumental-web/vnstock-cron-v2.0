import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { DEFAULT_SCORING_VERSION, REVIEW_VERSIONS } from "@/lib/scoring-versions";
import type { DashboardDataSource } from "@/lib/data-source/source";
import { fetchGitHubServing } from "@/lib/data-source/github-serving";

export interface ICMetricRow {
  config_version: string;
  factor: string;
  horizon: number;
  ic: number | null;
  n: number | null;
  computed_at: string | null;
}

export interface ICIndicatorRow {
  indicator: string;
  horizon: number;
  ic: number | null;
  n: number;
}

export interface ICFactorVersionRow {
  version: string;
  factor: string;
  horizon: number;
  ic: number | null;
  n: number;
}

export interface ICMarginalRow {
  version: string;
  indicator: string;
  factor: string | null;
  horizon: number;
  coef: number | null;
  tstat: number | null;
  univar_ic: number | null;
  n: number | null;
}

export interface ICIndustryRow {
  version: string;
  factor: string;
  industry: string;
  horizon: number;
  ic: number | null;
  n: number;
}

export interface ICDashboardSnapshot {
  schema_version: 1;
  release_id: string | null;
  generated_at: string | null;
  source: DashboardDataSource;
  metrics: ICMetricRow[];
  indicators: ICIndicatorRow[];
  factor_versions: ICFactorVersionRow[];
  marginal: ICMarginalRow[];
  industry: ICIndustryRow[];
  industry_errors: Record<string, string | null>;
  fallback_reason?: string;
}


async function loadSupabaseIC(): Promise<ICDashboardSnapshot> {
  const supabase = createCachedPublicClient("ic-metadata", DEFAULT_SCORING_VERSION);
  const { data } = await supabase
    .from("v4_ic_metrics")
    .select("config_version, factor, horizon, ic, n, computed_at")
    .order("config_version", { ascending: false })
    .order("factor", { ascending: true })
    .order("horizon", { ascending: true });

  const metrics = (data ?? []) as ICMetricRow[];
  const versions = REVIEW_VERSIONS.filter((version) =>
    metrics.some((row) => row.config_version === version),
  );
  const currentClient = createCachedPublicClient("ic", DEFAULT_SCORING_VERSION);
  const [indicatorResult, batchResult, perVersion] = await Promise.all([
    currentClient.from("v4_ic_by_indicator").select("indicator, horizon, ic, n"),
    currentClient
      .from("v4_ic_industry_batch")
      .select("batch_id, data_asof, computed_at")
      .eq("status", "ready")
      .order("computed_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    Promise.all(versions.map(async (version) => {
      const client = createCachedPublicClient("ic", version);
      const [factorResult, marginalResult] = await Promise.all([
        client
          .from("v4_ic_by_factor_ver")
          .select("version, factor, horizon, ic, n")
          .eq("version", version),
        client
          .from("v4_marginal_ic")
          .select("version, indicator, factor, horizon, coef, tstat, univar_ic, n")
          .eq("version", version),
      ]);
      return {
        factorVersions: (factorResult.data ?? []) as ICFactorVersionRow[],
        marginal: (marginalResult.data ?? []) as ICMarginalRow[],
      };
    })),
  ]);

  const industryErrors: Record<string, string | null> = {};
  const industryResults = batchResult.data
    ? await Promise.all(versions.map(async (version) => {
        const client = createCachedPublicClient("ic", version);
        const result = await client
          .from("v4_ic_industry_metrics")
          .select("version, factor, industry, horizon, ic, n")
          .eq("batch_id", batchResult.data!.batch_id)
          .eq("version", version)
          .order("factor", { ascending: true })
          .order("industry", { ascending: true })
          .order("horizon", { ascending: true });
        industryErrors[version] = result.error?.message ?? null;
        return (result.data ?? []) as ICIndustryRow[];
      }))
    : versions.map((version) => {
        industryErrors[version] = batchResult.error?.message ?? null;
        return [] as ICIndustryRow[];
      });

  return {
    schema_version: 1,
    release_id: null,
    generated_at: null,
    source: "supabase",
    metrics,
    indicators: (indicatorResult.data ?? []) as ICIndicatorRow[],
    factor_versions: perVersion.flatMap((result) => result.factorVersions),
    marginal: perVersion.flatMap((result) => result.marginal),
    industry: industryResults.flat(),
    industry_errors: industryErrors,
  };
}

function isGitHubSnapshot(value: unknown): value is ICDashboardSnapshot {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ICDashboardSnapshot>;
  return candidate.schema_version === 1
    && Array.isArray(candidate.metrics)
    && Array.isArray(candidate.indicators)
    && Array.isArray(candidate.factor_versions)
    && Array.isArray(candidate.marginal)
    && Array.isArray(candidate.industry)
    && !!candidate.industry_errors
    && typeof candidate.industry_errors === "object";
}

async function loadGitHubIC(): Promise<ICDashboardSnapshot> {
  const snapshot: unknown = await fetchGitHubServing("ic.json");
  if (!isGitHubSnapshot(snapshot)) throw new Error("GitHub IC snapshot has an unsupported schema");
  return { ...snapshot, source: "github" };
}
/**
 * IC is the first dual-source dashboard dataset. Supabase remains the default,
 * and GitHub failures fall back to Supabase until the shadow snapshots are proven.
 */
export async function getICDashboardSnapshot(
  source: DashboardDataSource = "supabase",
): Promise<ICDashboardSnapshot> {
  if (source === "supabase") return loadSupabaseIC();

  try {
    return await loadGitHubIC();
  } catch (error) {
    const fallback = await loadSupabaseIC();
    return {
      ...fallback,
      fallback_reason: error instanceof Error ? error.message : "Unknown GitHub serving error",
    };
  }
}
