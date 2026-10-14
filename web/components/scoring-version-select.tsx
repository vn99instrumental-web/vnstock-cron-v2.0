"use client";

import { useRouter } from "next/navigation";
import { availableReviewVersions, versionLabel } from "@/lib/scoring-versions";

export function ScoringVersionSelect({
  currentVersion,
  versions,
  route,
  dates = {},
  compact = false,
}: {
  currentVersion: string;
  versions: string[];
  route: string;
  dates?: Record<string, string>;
  compact?: boolean;
}) {
  const router = useRouter();
  const orderedVersions = availableReviewVersions(versions);
  return (
    <label className={`inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] ${compact ? "touch-target min-h-8 px-2 py-1 text-xs" : "min-h-10 px-3 py-2 text-sm"}`}>
      <span className="whitespace-nowrap text-[var(--color-muted)]">Scoring version</span>
      <select
        aria-label="Chọn scoring version"
        className={`rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 font-mono font-semibold ${compact ? "min-h-7 text-xs" : "min-h-8 text-sm"}`}
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
