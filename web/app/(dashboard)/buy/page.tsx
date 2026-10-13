import { PageHeader } from "@/components/ui";
import { BuyBoard, type BuySignal, type ExpectancyRow, type RobustnessRow } from "@/components/buy-board";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { getCompanyName } from "@/lib/company-names";
import { DEFAULT_SCORING_VERSION, isReviewVersion } from "@/lib/scoring-versions";

export const dynamic = "force-dynamic";

type BuyPageProps = { searchParams: Promise<{ version?: string }> };

export default async function BuyPage({ searchParams }: BuyPageProps) {
  const params = await searchParams;
  const supabase = createCachedPublicClient("version-metadata", DEFAULT_SCORING_VERSION);

  const productionVersion = DEFAULT_SCORING_VERSION;
  const { data: recentRuns } = await supabase
    .from("v4_runs")
    .select("run_id, started_at, scoring_version")
    .not("scoring_version", "is", null)
    .order("started_at", { ascending: false })
    .limit(1000);
  const versionDates: Record<string, string> = {};
  for (const item of recentRuns ?? []) {
    const version = String(item.scoring_version);
    if (!isReviewVersion(version)) continue;
    if (!versionDates[version]) versionDates[version] = String(item.run_id).split("_")[0];
  }
  const requestedVersion = typeof params.version === "string" ? params.version : productionVersion;
  const currentVersion = isReviewVersion(requestedVersion) && versionDates[requestedVersion] ? requestedVersion : productionVersion;
  const dataClient = createCachedPublicClient("buy", currentVersion);

  // Run MỚI NHẤT CÓ tín hiệu BUY thực sự trong v4_signals (bền vững kể cả khi run
  // mới nhất chưa sync đủ signals, hoặc tình cờ 0 BUY).
  const { data: latestBuy } = await dataClient
    .from("v4_signals")
    .select("run_id, signal_date, snap_time")
    .in("decision", ["BUY", "STRONG BUY"])
    .eq("scoring_version", currentVersion)
    .order("signal_date", { ascending: false })
    .order("snap_time", { ascending: false })
    .limit(1)
    .maybeSingle();

  // So với run mới nhất tổng thể (để báo nếu đang xem run cũ hơn).
  const { data: newestRun } = await dataClient
    .from("v4_runs")
    .select("run_id")
    .order("started_at", { ascending: false })
    .eq("scoring_version", currentVersion)
    .limit(1)
    .maybeSingle();

  const { data } = latestBuy
    ? await dataClient
        .from("v4_signals")
        .select("id, symbol, decision, score_trade, signal_date, breakdown")
        .eq("run_id", latestBuy.run_id)
        .eq("scoring_version", currentVersion)
        .in("decision", ["BUY", "STRONG BUY"])
        .order("score_trade", { ascending: false })
    : { data: [] };

  const signals = ((data ?? []) as BuySignal[]).map((signal) => ({
    ...signal,
    companyName: getCompanyName(signal.symbol),
  }));

  // % thay đổi so với giá TC (giá đóng cửa phiên liền trước) — lấy prevClose từ v4_ohlc.
  if (signals.length) {
    const sigDate = latestBuy!.signal_date as string;
    const since = new Date(new Date(sigDate).getTime() - 14 * 864e5).toISOString().slice(0, 10);
    const { data: ohlc } = await dataClient
      .from("v4_ohlc")
      .select("symbol, date, close")
      .in("symbol", signals.map((s) => s.symbol))
      .lt("date", sigDate)
      .gte("date", since)
      .order("date", { ascending: false });
    const prev = new Map<string, number>();
    for (const r of (ohlc ?? []) as { symbol: string; close: number }[]) {
      if (!prev.has(r.symbol)) prev.set(r.symbol, Number(r.close));
    }
    for (const s of signals) {
      const price = Number((s.breakdown ?? {}).price);
      const pc = prev.get(s.symbol);
      s.changePct = pc && Number.isFinite(price) && pc !== 0 ? ((price - pc) / pc) * 100 : null;
    }
  }
  // Thời điểm run (độ tươi data) + kỳ vọng lịch sử của BUY theo confidence.
  const { data: runRow } = latestBuy
    ? await dataClient
        .from("v4_runs")
        .select("started_at")
        .eq("run_id", latestBuy.run_id)
        .eq("scoring_version", currentVersion)
        .maybeSingle()
    : { data: null };
  const { data: expData } = await dataClient
    .from("v4_buy_expectancy")
    .select("*")
    .eq("scoring_version", currentVersion);

  // Độ tươi data (tính server-side để gộp thẳng vào dòng header, tiết kiệm 1 dòng).
  const startedAt = (runRow?.started_at as string | undefined) ?? null;
  let freshTxt = "";
  if (startedAt) {
    const min = Math.max(0, Math.round((Date.now() - new Date(startedAt).getTime()) / 60000));
    const ago = min < 1 ? "vừa xong" : min < 60 ? `${min} phút trước` : (() => {
      const h = Math.floor(min / 60);
      return h < 24 ? `${h} giờ trước` : `${Math.floor(h / 24)} ngày trước`;
    })();
    const ict = new Date(Date.now() + 7 * 3600e3);
    const dow = ict.getUTCDay();
    const hh = ict.getUTCHours() + ict.getUTCMinutes() / 60;
    const marketOpen = dow >= 1 && dow <= 5 && hh >= 9 && hh <= 15;
    freshTxt = ` · Run ${latestBuy!.run_id} · cập nhật ${ago} · ${marketOpen ? "phiên ĐANG MỞ" : "ngoài phiên"}`;
  }

  // D/E/F — độ vững tín hiệu (thanh khoản từ breakdown; độ bền/đồng thuận từ view).
  const { data: robData } = await dataClient
    .from("v4_buy_robustness")
    .select("*")
    .eq("scoring_version", currentVersion);

  // IC score↔lợi nhuận 5 phiên theo ngành (badge chất lượng ngành trong danh sách).
  const { data: indusICData } = await dataClient
    .from("v4_ic_by_industry_ver")
    .select("industry, ic, n")
    .eq("version", currentVersion)
    .eq("horizon", 5);
  const industryIC: Record<string, { ic: number | null; n: number }> = {};
  for (const r of (indusICData ?? []) as { industry: string; ic: number | string | null; n: number }[]) {
    industryIC[r.industry] = { ic: r.ic == null ? null : Number(r.ic), n: Number(r.n) };
  }

  return (
    <>
      <PageHeader
        title="Mua"
        desc={`${currentVersion} · ${signals.length} mã BUY / STRONG BUY${freshTxt}`}
      />
      <BuyBoard
        signals={signals}
        expectancy={(expData ?? []) as ExpectancyRow[]}
        robustness={(robData ?? []) as RobustnessRow[]}
        runId={latestBuy?.run_id}
        runStartedAt={(runRow?.started_at as string | undefined) ?? null}
        newestRunId={(newestRun?.run_id as string | undefined) ?? null}
        industryIC={industryIC}
        currentVersion={currentVersion}
        versionDates={versionDates}
      />
    </>
  );
}
