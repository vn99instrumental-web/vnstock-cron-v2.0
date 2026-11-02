import { PageHeader } from "@/components/ui";
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
  let freshTxt = "";
  if (startedAt && data.latestBuy?.run_id) {
    const min = Math.max(0, Math.round((Date.now() - new Date(startedAt).getTime()) / 60000));
    const ago = min < 1 ? "vừa xong" : min < 60 ? `${min} phút trước` : Math.floor(min / 60) < 24 ? `${Math.floor(min / 60)} giờ trước` : `${Math.floor(min / 1440)} ngày trước`;
    const ict = new Date(Date.now() + 7 * 3600e3), dow = ict.getUTCDay(), hh = ict.getUTCHours() + ict.getUTCMinutes() / 60;
    freshTxt = ` · Run ${data.latestBuy.run_id} · cập nhật ${ago} · ${dow >= 1 && dow <= 5 && hh >= 9 && hh <= 15 ? "phiên ĐANG MỞ" : "ngoài phiên"}`;
  }
  return <>
    <PageHeader title="Mua" desc={`${currentVersion} Â· ${data.signals.length} mÃ£ BUY / STRONG BUY${freshTxt}`} actions={<ScoringVersionSelect currentVersion={currentVersion} versions={Object.keys(versionDates)} route="/buy" dates={versionDates} compact />} />
    <BuyBoard signals={data.signals} expectancy={data.expectancy} robustness={data.robustness}
      runId={data.latestBuy?.run_id} runStartedAt={startedAt} newestRunId={data.newestRun?.run_id}
      industryIC={data.industryIC} currentVersion={currentVersion} />
  </>;
}
