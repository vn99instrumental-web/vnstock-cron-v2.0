// UI primitives dùng chung (data-dense, trung tính). Nhãn tiếng Việt.

export function PageHeader({
  title,
  desc,
}: {
  title: string;
  desc?: string;
}) {
  return (
    <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-0">
      <h1 className="shrink-0 text-base font-bold leading-tight tracking-tight sm:text-lg">{title}</h1>
      {desc ? (
        <p className="text-[12px] leading-tight text-[var(--color-muted)]">{desc}</p>
      ) : null}
    </div>
  );
}

export function Card({ children }: { children: React.ReactNode }) {
  return <div className="card p-4 sm:p-5">{children}</div>;
}

export interface InsightMetric {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  tone?: "default" | "positive" | "negative" | "warning";
}

/** Dải KPI đặt dưới header: ưu tiên khả năng quét nhanh, không biến header thành dashboard. */
export function InsightStrip({ metrics, className = "" }: { metrics: InsightMetric[]; className?: string }) {
  const toneClass = (tone: InsightMetric["tone"]) => {
    if (tone === "positive") return "text-[var(--color-buy)]";
    if (tone === "negative") return "text-[var(--color-sell)]";
    if (tone === "warning") return "text-amber-600 dark:text-amber-400";
    return "text-[var(--color-ink)]";
  };
  return (
    <div className={`insight-strip mb-3 grid gap-1.5 ${className}`}>
      {metrics.map((metric) => (
        <div key={metric.label} className="card min-w-0 px-3 py-2">
          <div className={`tabular truncate text-base font-semibold leading-tight ${toneClass(metric.tone)}`}>{metric.value}</div>
          <div className="mt-0.5 text-[11px] font-medium text-[var(--color-muted)]">{metric.label}</div>
          {metric.detail != null ? <div className="mt-0.5 truncate text-[10px] text-[var(--color-muted)]">{metric.detail}</div> : null}
        </div>
      ))}
    </div>
  );
}

/** Empty state — dùng khi bảng chưa có data (chờ sync). */
export function EmptyState({
  title = "Chưa có dữ liệu",
  hint,
}: {
  title?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      {hint ? (
        <p className="mx-auto mt-1 max-w-md text-xs text-[var(--color-muted)]">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function QueryErrorState({
  title = "Không tải được dữ liệu",
  hint = "Hãy tải lại trang. Nếu lỗi còn lặp lại, kiểm tra trạng thái đồng bộ dữ liệu.",
}: {
  title?: string;
  hint?: string;
}) {
  return (
    <div role="alert" className="rounded-lg border border-[var(--color-sell)]/40 bg-[var(--color-sell)]/5 px-5 py-8 text-center">
      <p className="text-sm font-semibold text-[var(--color-sell)]">{title}</p>
      <p className="mx-auto mt-1 max-w-lg text-xs text-[var(--color-muted)]">{hint}</p>
    </div>
  );
}
/** Badge màu theo decision (semantic). */
const DECISION_STYLES: Record<string, string> = {
  "STRONG BUY": "bg-[var(--color-strong-buy)] text-white",
  BUY: "bg-[var(--color-buy)] text-white",
  NEUTRAL: "bg-[var(--color-neutral)]/15 text-[var(--color-neutral)]",
  SELL: "bg-[var(--color-sell)] text-white",
  "STRONG SELL": "bg-[var(--color-strong-sell)] text-white",
};

export function DecisionBadge({ decision }: { decision: string | null }) {
  const key = (decision ?? "").toUpperCase();
  const cls = DECISION_STYLES[key] ?? "bg-black/10 text-[var(--color-muted)]";
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold tracking-tight ${cls}`}
    >
      {decision ?? "—"}
    </span>
  );
}
