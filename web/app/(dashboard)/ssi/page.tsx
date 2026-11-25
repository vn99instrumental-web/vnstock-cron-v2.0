import { TodayPageView } from "@/components/today-page-view";

export const dynamic = "force-dynamic";

export default function SsiIndependentPage() {
  return <TodayPageView forcedSource="ssi" />;
}
