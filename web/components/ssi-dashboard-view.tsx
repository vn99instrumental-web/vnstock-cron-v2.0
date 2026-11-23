import { InsightStrip, PageHeader, QueryErrorState } from "@/components/ui";
import { SsiOfflineComparison } from "@/components/ssi-offline-comparison";
import { SsiV418ShadowPanel } from "@/components/ssi-v418-shadow-panel";
import { getSsiV418OfflineEvidence } from "@/lib/ssi-v418-offline";
import { getSsiV418Shadow } from "@/lib/ssi-v418-shadow";

export type SsiDashboardTab = "buy" | "today" | "analysis" | "history" | "ic";

const TITLES: Record<SsiDashboardTab, string> = {
  buy: "Mua",
  today: "H\u00f4m nay",
  analysis: "Ph\u00e2n t\u00edch",
  history: "L\u1ecbch s\u1eed",
  ic: "Ch\u1ea5t l\u01b0\u1ee3ng (IC)",
};

function Missing({ reason }: { reason: string }) {
  return (
    <span
      className="inline-flex rounded-md border border-amber-500/50 bg-amber-500/10 px-2 py-1 text-[11px] font-semibold text-amber-700 dark:text-amber-300"
      title={reason}
    >
      {"Thi\u1ebfu"}
    </span>
  );
}

function Guardrail() {
  return (
    <div role="status" className="mb-3 rounded-lg border border-amber-500/50 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed">
      <strong>{"SSI source-only \u2014 NOT FOR TRADING."}</strong>{" "}
      {"D\u1eef li\u1ec7u thi\u1ebfu \u0111\u01b0\u1ee3c gi\u1eef l\u00e0 null v\u00e0 highlight; kh\u00f4ng \u0111i\u1ec1n 0, kh\u00f4ng \u0111\u1ed5i tr\u1ecdng s\u1ed1, kh\u00f4ng t\u1ea1o BUY/SELL."}
    </div>
  );
}

function AvailabilityTable({ tab }: { tab: "buy" | "today" | "history" }) {
  const offline = getSsiV418OfflineEvidence()!;
  const shadow = getSsiV418Shadow()!;
  const shadowBySymbol = new Map(shadow.rows.map((row) => [row.symbol, row]));
  return (
    <div className="max-h-[620px] overflow-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full min-w-[800px] border-collapse text-left text-xs">
        <thead className="sticky top-0 z-10 bg-[var(--color-surface)] text-[11px] text-[var(--color-muted)]">
          <tr className="border-b border-[var(--color-border)]">
            <th className="px-3 py-2">{"M\u00e3"}</th>
            <th className="px-3 py-2">{"Ng\u00e0y d\u1eef li\u1ec7u"}</th>
            <th className="px-3 py-2 text-right">{"Gi\u00e1 SSI"}</th>
            <th className="px-3 py-2 text-right">{"\u1ee8ng vi\u00ean t\u00edn hi\u1ec7u"}</th>
            <th className="px-3 py-2">{"\u0110i\u1ec3m / quy\u1ebft \u0111\u1ecbnh"}</th>
            <th className="px-3 py-2">{tab === "history" ? "Outcome / IC" : "Score / BUY/SELL"}</th>
          </tr>
        </thead>
        <tbody>
          {offline.rows.map((row) => {
            const detail = shadowBySymbol.get(row.symbol);
            return (
              <tr key={row.symbol} className="border-b border-[var(--color-border)]/60 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]">
                <td className="px-3 py-2 font-bold">{row.symbol}</td>
                <td className="px-3 py-2 tabular">{row.trade_date}</td>
                <td className={`px-3 py-2 text-right tabular ${row.ssi_close_as_reported_vnd == null ? "bg-amber-500/10" : ""}`}>
                  {row.ssi_close_as_reported_vnd == null
                    ? <Missing reason="SSI close unavailable" />
                    : Number(row.ssi_close_as_reported_vnd).toLocaleString("vi-VN")}
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {detail?.candidate_signal_count ?? 0}/17
                </td>
                <td className="bg-amber-500/10 px-3 py-2">
                  <Missing reason="17 signal values are not parity-certified" />
                </td>
                <td className="bg-amber-500/10 px-3 py-2">
                  <Missing reason={tab === "history" ? "No forward outcome series" : "Official score and decision are blocked"} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function IcContract() {
  const offline = getSsiV418OfflineEvidence()!;
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {offline.signals.map((signal) => (
        <div key={signal.id} className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
          <div className="flex items-center justify-between gap-2">
            <strong className="font-mono text-xs">{signal.id}</strong>
            <Missing reason="Signal parity is not certified" />
          </div>
          <p className="mt-2 text-xs font-medium">{signal.factor}</p>
          <p className="mt-1 break-words font-mono text-[10px] text-[var(--color-muted)]">{signal.source_readiness}</p>
        </div>
      ))}
    </div>
  );
}

export function SsiDashboardView({ tab }: { tab: SsiDashboardTab }) {
  const offline = getSsiV418OfflineEvidence();
  const shadow = getSsiV418Shadow();
  if (!offline || !shadow) {
    return <QueryErrorState title="SSI artifact validation failed" hint="No SSI score or decision is displayed." />;
  }
  const descriptions: Record<SsiDashboardTab, string> = {
    buy: "0 BUY/SELL ch\u00ednh th\u1ee9c \u2014 highlight c\u00e1c input c\u00f2n thi\u1ebfu",
    today: `${offline.rows.length} m\u00e3 \u2014 snapshot ${offline.source_trade_date} \u2014 kh\u00f4ng realtime`,
    analysis: "17 t\u00edn hi\u1ec7u/m\u00e3 \u2014 partial contribution kh\u00f4ng ph\u1ea3i t\u1ed5ng \u0111i\u1ec3m",
    history: "1 snapshot \u2014 ch\u01b0a c\u00f3 chu\u1ed7i outcome ti\u1ebfn v\u1ec1 tr\u01b0\u1edbc",
    ic: "0 score ch\u00ednh th\u1ee9c \u2014 0 outcome \u2014 IC ch\u01b0a th\u1ec3 t\u00ednh",
  };
  return (
    <>
      <PageHeader
        title={TITLES[tab]}
        desc={descriptions[tab]}
        actions={
          <span className="rounded-md border border-red-500/40 bg-red-500/5 px-2 py-1 text-[10px] font-semibold text-[var(--color-sell)]">
            {"SSI \u2014 NOT FOR TRADING"}
          </span>
        }
      />
      <InsightStrip className="sm:grid-cols-4" metrics={[
        { label: "SSI symbols", value: shadow.summary.cohort_symbols, tone: "positive" },
        { label: "Signal contract", value: `${shadow.summary.max_active_signals}/17` },
        { label: "Official scores", value: shadow.summary.official_trade_scores, tone: "warning" },
        { label: "BUY/SELL", value: shadow.summary.official_buy_sell_decisions, tone: "warning" },
      ]} />
      <Guardrail />
      {tab === "today" ? <><AvailabilityTable tab="today" /><div className="mt-3"><SsiOfflineComparison data={offline} /></div></> : null}
      {tab === "analysis" ? <SsiV418ShadowPanel data={shadow} /> : null}
      {tab === "buy" || tab === "history" ? <AvailabilityTable tab={tab} /> : null}
      {tab === "ic" ? (
        <section className="card p-4 sm:p-5">
          <div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs">
            <strong>{"Ch\u01b0a \u0111\u1ee7 d\u1eef li\u1ec7u:"}</strong>{" "}
            {"IC c\u1ea7n score ch\u00ednh th\u1ee9c v\u00e0 outcome theo horizon. C\u1ea3 hai hi\u1ec7n \u0111ang null, n\u00ean kh\u00f4ng hi\u1ec3n th\u1ecb h\u1ec7 s\u1ed1 gi\u1ea3."}
          </div>
          <IcContract />
        </section>
      ) : null}
    </>
  );
}
