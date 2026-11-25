import { InsightStrip, PageHeader, QueryErrorState } from "@/components/ui";
import { getSsiIndependentDashboard, type SsiDecision, type SsiHistoryRow, type SsiLatestRow } from "@/lib/ssi-independent";

export type SsiDashboardTab = "buy" | "today" | "analysis" | "history" | "ic";
const TITLES: Record<SsiDashboardTab, string> = { buy: "Mua", today: "Hôm nay", analysis: "Phân tích", history: "Lịch sử", ic: "Chất lượng (IC)" };

function fmt(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? "—" : value.toLocaleString("vi-VN", { maximumFractionDigits: digits });
}
function decisionClass(value: SsiDecision): string {
  if (value === "BUY" || value === "STRONG BUY") return "text-[var(--color-buy)]";
  if (value === "SELL" || value === "STRONG SELL") return "text-[var(--color-sell)]";
  return "text-[var(--color-muted)]";
}
function SourceNotice() {
  return <div role="status" className="mb-3 rounded-lg border border-blue-500/40 bg-blue-500/5 px-3 py-2 text-xs leading-relaxed">
    <strong>Bộ tính SSI độc lập.</strong>{" "}Dùng chung lớp dữ liệu SSI + FHSC với Gen6 nhưng tự tính lại 17 tín hiệu, factor, score và decision; không đọc <code>s_*</code>, <code>score_trade</code> hoặc decision của Gen6. Tín hiệu phục vụ nghiên cứu, không phải khuyến nghị đầu tư.
  </div>;
}
function Coverage({ row }: { row: SsiLatestRow }) {
  const full = row.signal_coverage === row.signal_count;
  return <span className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-semibold ${full ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300"}`} title={row.missing_signals.length ? `Thiếu: ${row.missing_signals.join(", ")}` : "Đủ 17 tín hiệu"}>{row.signal_coverage}/{row.signal_count}</span>;
}
function LatestTable({ rows, analysis = false }: { rows: SsiLatestRow[]; analysis?: boolean }) {
  if (!rows.length) return <div className="card p-5 text-sm text-[var(--color-muted)]">Không có mã phù hợp trong snapshot hiện tại.</div>;
  return <div className="max-h-[680px] overflow-auto rounded-lg border border-[var(--color-border)]">
    <table className={`w-full border-collapse text-left text-xs ${analysis ? "min-w-[1120px]" : "min-w-[860px]"}`}>
      <thead className="sticky top-0 z-10 bg-[var(--color-surface)] text-[11px] text-[var(--color-muted)]"><tr className="border-b border-[var(--color-border)]">
        <th className="px-3 py-2">Mã</th><th className="px-3 py-2">Ngày / giờ</th><th className="px-3 py-2 text-right">Giá</th><th className="px-3 py-2 text-right">Trade</th><th className="px-3 py-2 text-right">Hold</th><th className="px-3 py-2">Decision</th><th className="px-3 py-2">Coverage</th><th className="px-3 py-2">Regime</th>
        {analysis ? <><th className="px-3 py-2 text-right">Mean rev.</th><th className="px-3 py-2 text-right">Breakout</th><th className="px-3 py-2 text-right">Flow</th><th className="px-3 py-2 text-right">Fund.</th><th className="px-3 py-2 text-right">Growth</th></> : null}
      </tr></thead>
      <tbody>{rows.map((row) => <tr key={row.pred_id} className="border-b border-[var(--color-border)]/60 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]">
        <td className="px-3 py-2 font-bold">{row.symbol}</td><td className="px-3 py-2 tabular">{row.signal_date} · {row.snap_time}</td><td className="px-3 py-2 text-right tabular">{fmt(row.price)}</td><td className="px-3 py-2 text-right font-semibold tabular">{fmt(row.score_trade)}</td><td className="px-3 py-2 text-right tabular">{fmt(row.score_hold)}</td><td className={`px-3 py-2 font-semibold ${decisionClass(row.decision)}`}>{row.decision}</td><td className="px-3 py-2"><Coverage row={row} /></td><td className="px-3 py-2 font-mono text-[10px]">{row.regime}</td>
        {analysis ? <><td className="px-3 py-2 text-right tabular">{fmt(row.factors.mean_reversion, 3)}</td><td className="px-3 py-2 text-right tabular">{fmt(row.factors.breakout, 3)}</td><td className="px-3 py-2 text-right tabular">{fmt(row.factors.flow, 3)}</td><td className="px-3 py-2 text-right tabular">{fmt(row.factors.fundamental, 3)}</td><td className="px-3 py-2 text-right tabular">{fmt(row.factors.growth, 3)}</td></> : null}
      </tr>)}</tbody>
    </table>
  </div>;
}
function HistoryTable({ rows }: { rows: SsiHistoryRow[] }) {
  return <div className="max-h-[680px] overflow-auto rounded-lg border border-[var(--color-border)]"><table className="w-full min-w-[900px] border-collapse text-left text-xs">
    <thead className="sticky top-0 z-10 bg-[var(--color-surface)] text-[11px] text-[var(--color-muted)]"><tr className="border-b border-[var(--color-border)]"><th className="px-3 py-2">Ngày</th><th className="px-3 py-2">Mã</th><th className="px-3 py-2 text-right">Giá</th><th className="px-3 py-2 text-right">Score</th><th className="px-3 py-2">Decision</th><th className="px-3 py-2 text-right">D+3</th><th className="px-3 py-2 text-right">D+5</th><th className="px-3 py-2 text-right">D+10</th><th className="px-3 py-2">Coverage</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.pred_id} className="border-b border-[var(--color-border)]/60"><td className="px-3 py-2 tabular">{row.signal_date} · {row.snap_time}</td><td className="px-3 py-2 font-bold">{row.symbol}</td><td className="px-3 py-2 text-right tabular">{fmt(row.price)}</td><td className="px-3 py-2 text-right font-semibold tabular">{fmt(row.score_trade)}</td><td className={`px-3 py-2 font-semibold ${decisionClass(row.decision)}`}>{row.decision}</td><td className="px-3 py-2 text-right tabular">{row.ret_3d == null ? "—" : `${fmt(row.ret_3d)}%`}</td><td className="px-3 py-2 text-right tabular">{row.ret_5d == null ? "—" : `${fmt(row.ret_5d)}%`}</td><td className="px-3 py-2 text-right tabular">{row.ret_10d == null ? "Đang chờ" : `${fmt(row.ret_10d)}%`}</td><td className="px-3 py-2 tabular">{row.signal_coverage}/17</td></tr>)}</tbody>
  </table></div>;
}

export function SsiDashboardView({ tab }: { tab: SsiDashboardTab }) {
  const data = getSsiIndependentDashboard();
  if (!data) return <QueryErrorState title="SSI dataset validation failed" hint="Artifact không đạt schema/source guard nên không hiển thị score." />;
  const buyRows = data.latest.filter((row) => row.decision === "BUY" || row.decision === "STRONG BUY");
  const descriptions: Record<SsiDashboardTab, string> = { buy: `${buyRows.length} tín hiệu BUY/STRONG BUY · snapshot ${data.signal_date}`, today: `${data.summary.symbols} mã · snapshot ${data.signal_date} · SSI + FHSC`, analysis: "17 tín hiệu · factor và score do SSI calculator độc lập tính lại", history: `${data.summary.history_rows} dự báo · ${data.summary.history_dates} phiên nguồn`, ic: "IC Pearson từ outcome thực đã đủ horizon" };
  return <><PageHeader title={TITLES[tab]} desc={descriptions[tab]} actions={<span className="rounded-md border border-blue-500/40 bg-blue-500/5 px-2 py-1 text-[10px] font-semibold text-blue-700 dark:text-blue-300">SSI độc lập · v4.18</span>} />
    <InsightStrip className="sm:grid-cols-4" metrics={[{ label: "SSI symbols", value: data.summary.symbols, tone: "positive" }, { label: "Đủ 17/17", value: data.summary.full_17_signal_rows }, { label: "BUY", value: data.summary.buy, tone: "positive" }, { label: "SELL", value: data.summary.sell, tone: "warning" }]} />
    <SourceNotice />
    {tab === "today" ? <LatestTable rows={data.latest} /> : null}{tab === "buy" ? <LatestTable rows={buyRows} /> : null}{tab === "analysis" ? <LatestTable rows={data.latest} analysis /> : null}{tab === "history" ? <HistoryTable rows={data.history} /> : null}
    {tab === "ic" ? <section className="grid gap-3 sm:grid-cols-3">{([3, 5, 10] as const).map((horizon) => { const metric = data.ic[`ret_${horizon}d`]; return <div key={horizon} className="card p-4"><p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">D+{horizon}</p><p className="mt-2 text-2xl font-semibold tabular">{metric.pearson == null ? "Đang chờ" : fmt(metric.pearson, 4)}</p><p className="mt-1 text-xs text-[var(--color-muted)]">n={metric.n.toLocaleString("vi-VN")} outcome</p></div>; })}<div className="card p-4 text-xs leading-relaxed sm:col-span-3">D+10 chỉ xuất hiện sau khi đủ 10 phiên giao dịch tương lai. Scheduler tự bổ sung outcome và IC sau mỗi lần nguồn hoàn tất; không nội suy dữ liệu tương lai.</div></section> : null}
  </>;
}
