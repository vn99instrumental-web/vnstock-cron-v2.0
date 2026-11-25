import { AnalysisBoard, type SignalResult } from "@/components/analysis-board";
import { BuyBoard, type BuySignal } from "@/components/buy-board";
import { MissingDataNotice, MissingDataValue } from "@/components/missing-data";
import { ScoringVersionSelect } from "@/components/scoring-version-select";
import { SignalsTable, type SignalRow } from "@/components/signals-table";
import { InsightStrip, PageHeader } from "@/components/ui";
import { getCompanyName } from "@/lib/company-names";
import { SSI_SCORING_VERSION, ssiServing } from "@/lib/data-source/ssi-serving";
import { getSsiIndependentDashboard } from "@/lib/ssi-independent";

export type SsiAlignedTab = "buy" | "analysis" | "history" | "ic";

const ROUTES: Record<SsiAlignedTab, string> = {
  buy: "/ssi/buy",
  analysis: "/ssi/phan-tich",
  history: "/ssi/history",
  ic: "/ssi/ic",
};

function VersionAction({ tab }: { tab: SsiAlignedTab }) {
  return (
    <ScoringVersionSelect
      currentVersion={SSI_SCORING_VERSION}
      versions={[SSI_SCORING_VERSION]}
      route={ROUTES[tab]}
      compact
    />
  );
}

function SourceNotice() {
  return (
    <div className="mb-3 rounded-lg border border-blue-500/40 bg-blue-500/5 px-3 py-2 text-xs leading-relaxed">
      <strong>SSI độc lập.</strong>{" "}
      Dùng dữ liệu SSI/FHSC và bộ tính riêng; giao diện dùng chung component với Gen 6 để đối chiếu trực tiếp.
    </div>
  );
}

export async function SsiAlignedDashboard({ tab }: { tab: SsiAlignedTab }) {
  const dashboard = getSsiIndependentDashboard();
  if (!dashboard) throw new Error("SSI dashboard source/schema validation failed");

  if (tab === "buy") {
    const data = await ssiServing.buy(SSI_SCORING_VERSION);
    const signals = (data.signals as unknown as BuySignal[]).map((row) => ({ ...row, companyName: getCompanyName(row.symbol) }));
    return (
      <>
        <PageHeader title="Mua" desc={`${signals.length} tín hiệu BUY/STRONG BUY · ${dashboard.signal_date}`} actions={<VersionAction tab={tab} />} />
        <MissingDataNotice items={["Biểu đồ OHLC độc lập", "Expectancy", "Robustness 15 phiên", "IC theo ngành"]} />
        <SourceNotice />
        <BuyBoard
          signals={signals}
          expectancy={[]}
          robustness={[]}
          runId={String(data.latestBuy?.run_id ?? "")}
          runStartedAt={String(data.runRow?.started_at ?? dashboard.generated_at)}
          newestRunId={String(data.newestRun?.run_id ?? "")}
          industryIC={{}}
          currentVersion={SSI_SCORING_VERSION}
          dataSource="ssi"
        />
      </>
    );
  }

  if (tab === "analysis") {
    const data = await ssiServing.analysis(SSI_SCORING_VERSION);
    return (
      <>
        <PageHeader title="Phân tích" desc={`SSI độc lập · ${dashboard.summary.history_rows} dự báo`} actions={<VersionAction tab={tab} />} />
        <MissingDataNotice items={["Tương quan factor", "Ma trận cặp biến", "MFE/MAE", "Kết quả TP/SL chuẩn"]} />
        <SourceNotice />
        <AnalysisBoard results={data.results as unknown as SignalResult[]} corr={[]} pairs={[]} split={[]} />
      </>
    );
  }

  if (tab === "history") {
    const data = await ssiServing.history(SSI_SCORING_VERSION);
    const rows = (data.rows as unknown as SignalRow[]).slice(0, 200).map((row) => ({ ...row, companyName: getCompanyName(row.symbol) }));
    return (
      <>
        <PageHeader title="Lịch sử" desc={`${data.count.toLocaleString("vi-VN")} tín hiệu · SSI độc lập`} actions={<VersionAction tab={tab} />} />
        <MissingDataNotice items={["Regime lịch sử", "MFE/MAE cho các outcome chưa thu thập"]} />
        <SourceNotice />
        <SignalsTable rows={rows} showDate />
      </>
    );
  }

  const horizons = [3, 5, 10] as const;
  return (
    <>
      <PageHeader title="Chất lượng (IC)" desc="SSI độc lập · outcome forward theo horizon" actions={<VersionAction tab={tab} />} />
      <MissingDataNotice items={["Spearman IC theo factor", "IC theo chỉ báo", "IC theo ngành", "Marginal IC"]} />
      <SourceNotice />
      <InsightStrip
        className="sm:grid-cols-4"
        metrics={[
          { label: "Phiên nguồn", value: dashboard.summary.history_dates },
          { label: "Dự báo", value: dashboard.summary.history_rows },
          { label: "Đủ 17/17", value: dashboard.summary.full_17_signal_rows },
          { label: "Coverage thấp nhất", value: `${dashboard.summary.minimum_signal_coverage}/17`, tone: dashboard.summary.minimum_signal_coverage === 17 ? "positive" : "warning" },
        ]}
      />
      <section className="grid gap-3 sm:grid-cols-3">
        {horizons.map((horizon) => {
          const metric = dashboard.ic[`ret_${horizon}d`];
          return (
            <div key={horizon} className="card p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">D+{horizon}</p>
              <div className="mt-2 text-2xl font-semibold tabular">
                {metric.pearson == null ? <MissingDataValue /> : metric.pearson.toLocaleString("vi-VN", { maximumFractionDigits: 4 })}
              </div>
              <p className="mt-1 text-xs text-[var(--color-muted)]">Pearson hiện có · n={metric.n.toLocaleString("vi-VN")}</p>
            </div>
          );
        })}
      </section>
    </>
  );
}
