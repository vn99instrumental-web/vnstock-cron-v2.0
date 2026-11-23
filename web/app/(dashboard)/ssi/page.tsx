import { EmptyState, InsightStrip, PageHeader } from "@/components/ui";
import { SsiOfflineComparison } from "@/components/ssi-offline-comparison";
import { SsiV418ShadowPanel } from "@/components/ssi-v418-shadow-panel";
import { getSsiV418OfflineEvidence } from "@/lib/ssi-v418-offline";
import { getSsiV418Shadow } from "@/lib/ssi-v418-shadow";

export default function SsiIndependentPage() {
  const offline = getSsiV418OfflineEvidence();
  const shadow = getSsiV418Shadow();

  if (!offline || !shadow) {
    return (
      <>
        <PageHeader
          title="SSI independent"
          desc="The v4.18 engine uses SSI and Finhay data without the vnstock runtime."
        />
        <EmptyState
          title="Invalid SSI artifact"
          hint="SSI is fail-closed because the hash or data contract differs; there is no fallback to Gen6, Supabase, or GitHub."
        />
      </>
    );
  }

  return (
    <div className="space-y-3">
      <PageHeader
        title="SSI independent"
        desc={`v4.18 source-only - SSI + Finhay - snapshot ${shadow.source_trade_date} - no vnstock runtime`}
        actions={(
          <span className="rounded-md border border-red-500/40 bg-red-500/5 px-2.5 py-1 text-[11px] font-semibold text-[var(--color-sell)]">
            NOT FOR TRADING
          </span>
        )}
      />

      <section className="card border-amber-500/40 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--color-muted)]">
              Peer version - fail-closed
            </p>
            <h2 className="mt-1 text-base font-bold">Calculated from raw SSI and Finhay data</h2>
            <p className="mt-1 max-w-[920px] text-xs leading-relaxed text-[var(--color-muted)]">
              The formula, caps, weights, and 17-signal mapping use the frozen v4.18 reference.
              Missing values remain <code>null</code>; they are never imputed as zero or reweighted.
              This peer runs beside Gen 6 for data and parity checks; it does not replace production signals.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px] font-semibold">
            <span className="rounded-md border border-[var(--color-border)] px-2 py-1">SSI source-only</span>
            <span className="rounded-md border border-[var(--color-border)] px-2 py-1">Finhay fundamentals</span>
            <span className="rounded-md border border-amber-500/40 px-2 py-1 text-amber-700 dark:text-amber-300">BLOCKED_INPUT</span>
          </div>
        </div>
      </section>

      <InsightStrip
        className="sm:grid-cols-4"
        metrics={[
          { label: "SSI symbols", value: shadow.summary.cohort_symbols.toLocaleString("vi-VN"), tone: "positive" },
          { label: "Signal contract", value: `${shadow.summary.max_active_signals}/17` },
          { label: "Official scores", value: "0", tone: "warning" },
          { label: "BUY/SELL", value: "0", tone: "warning" },
        ]}
      />

      <SsiV418ShadowPanel data={shadow} />
      <SsiOfflineComparison data={offline} />
    </div>
  );
}
