// UI primitives dùng chung (data-dense, trung tính). Nhãn tiếng Việt.

export function PageHeader({
  title,
  desc,
}: {
  title: string;
  desc?: string;
}) {
  return (
    <div className="mb-5">
      <h1 className="text-lg font-semibold">{title}</h1>
      {desc ? (
        <p className="mt-1 text-sm text-[var(--color-muted)]">{desc}</p>
      ) : null}
    </div>
  );
}

export function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      {children}
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
      className={`inline-flex rounded px-2 py-0.5 text-xs font-semibold ${cls}`}
    >
      {decision ?? "—"}
    </span>
  );
}
