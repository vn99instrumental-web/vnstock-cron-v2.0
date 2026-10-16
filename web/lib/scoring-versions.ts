export const REVIEW_VERSIONS = ["v4.19-shadow", "v4.18", "v4.17", "v4.8", "v4.1", "v2.3"] as const;
export type ReviewVersion = (typeof REVIEW_VERSIONS)[number];
export const DEFAULT_SCORING_VERSION: ReviewVersion = "v4.19-shadow";

export function isReviewVersion(value: unknown): value is ReviewVersion {
  return typeof value === "string" && REVIEW_VERSIONS.includes(value as ReviewVersion);
}

export function availableReviewVersions(available: Iterable<string>): ReviewVersion[] {
  const values = new Set(available);
  return REVIEW_VERSIONS.filter((version) => values.has(version));
}

export function versionLabel(version: string): string {
  if (version === "v4.19-shadow") return "v4.19 · Shadow IC-weighted";
  return version === "v2.3" ? "v2.3 · Legacy" : version;
}
