"use client";

import { useRouter } from "next/navigation";
import { availableReviewVersions, versionLabel } from "@/lib/scoring-versions";

export function ScoringVersionSelect({
  currentVersion,
  versions,
  route,
  dates = {},
}: {
  currentVersion: string;
  versions: string[];
  route: string;
  dates?: Record<string, string>;
}) {
  const router = useRouter();
  const orderedVersions = availableReviewVersions(versions);
  return (
    <label className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm">
      <span className="whitespace-nowrap text-[var(--color-muted)]">Scoring version</span>
      <select
        aria-label="Chọn scoring version"
        className="min-h-8 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 font-mono text-sm font-semibold"
        value={currentVersion}
        onChange={(event) => router.push(`${route}?version=${encodeURIComponent(event.target.value)}`)}
      >
        {orderedVersions.map((version) => (
          <option key={version} value={version}>
            {versionLabel(version)}{dates[version] ? ` · ${dates[version]}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
