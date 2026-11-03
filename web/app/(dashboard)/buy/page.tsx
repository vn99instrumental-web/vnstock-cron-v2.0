import { PageHeader } from "@/components/ui";
import { dateTimeVN } from "@/lib/format";
import { BuyBoard } from "@/components/buy-board";
import { ScoringVersionSelect } from "@/components/scoring-version-select";
import { getLatestVersionRuns, resolveReviewVersion } from "@/lib/dashboard-data";
import { getBuyPageData } from "@/lib/data-source/buy";
import { getDashboardDataSource } from "@/lib/data-source/source";

export const dynamic = "force-dynamic";
type BuyPageProps = { searchParams: Promise<{ version?: string }> };

export default async function BuyPage({ searchParams }: BuyPageProps) {
  const params = await searchParams;
  const requestedSource = await getDashboardDataSource();
  const metadata = await getLatestVersionRuns("buy-metadata", requestedSource);
  const currentVersion = resolveReviewVersion(params.version, metadata.byVersion);
  const versionDates = Object.fromEntries(Object.entries(metadata.versionDates).filter(([, value]) => !!value)) as Record<string, string>;
  const data = await getBuyPageData(currentVersion, metadata.source);
  const startedAt = data.runRow?.started_at ?? null;
  // Use the same BUY run as the signals being displayed, not the newer run
  // that may contain no BUY signals. Fall back to the run snapshot timestamp.
  const runTime = startedAt ?? data.latestBuy?.snap_time ?? null;
  const runDesc = runTime ? `${currentVersion} · ${dateTimeVN(runTime)}` : currentVersion;
  return <>
    <PageHeader title="Mua" desc={runDesc} actions={<ScoringVersionSelect currentVersion={currentVersion} versions={Object.keys(versionDates)} route="/buy" dates={versionDates} compact />} />
    <BuyBoard signals={data.signals} expectancy={data.expectancy} robustness={data.robustness}
      runId={data.latestBuy?.run_id} runStartedAt={startedAt} newestRunId={data.newestRun?.run_id}
      industryIC={data.industryIC} currentVersion={currentVersion} />
  </>;
}
