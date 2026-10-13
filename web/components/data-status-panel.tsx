export type DataStatusTone = "ok" | "warn" | "stale" | "unknown";

export interface DataStatusItem {
  label: string;
  value: string;
  detail: string;
  tone: DataStatusTone;
}

const TONE: Record<DataStatusTone, { dot: string; text: string }> = {
  ok: { dot: "bg-[var(--color-buy)]", text: "Đúng hạn" },
  warn: { dot: "bg-amber-500", text: "Cần theo dõi" },
  stale: { dot: "bg-[var(--color-sell)]", text: "Đang trễ" },
  unknown: { dot: "bg-[var(--color-muted)]", text: "Chưa xác định" },
};

/** Operational freshness lives below the unchanged page header. */
export function DataStatusPanel({ items }: { items: DataStatusItem[] }) {
  const worst = items.some((item) => item.tone === "stale")
    ? "Có nguồn dữ liệu đang trễ"
    : items.some((item) => item.tone === "warn" || item.tone === "unknown")
      ? "Có nguồn dữ liệu cần kiểm tra"
      : "Các nguồn dữ liệu đúng hạn";
  return (
    <details className="card mb-4 p-3">
      <summary className="flex min-h-8 cursor-pointer list-none items-center gap-2 text-sm font-semibold">
        <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${items.some((item) => item.tone === "stale") ? "bg-[var(--color-sell)]" : "bg-[var(--color-buy)]"}`} />
        Trạng thái dữ liệu
        <span className="text-xs font-normal text-[var(--color-muted)]">· {worst}</span>
        <span className="ml-auto text-xs font-normal text-[var(--color-muted)]">Chi tiết</span>
      </summary>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => {
          const tone = TONE[item.tone];
          return (
            <div key={item.label} className="rounded-lg border border-[var(--color-border)] p-3">
              <div className="flex items-center gap-2 text-xs text-[var(--color-muted)]">
                <span aria-hidden className={`h-2 w-2 rounded-full ${tone.dot}`} />{item.label}
              </div>
              <div className="mt-1 text-sm font-semibold tabular">{item.value}</div>
              <div className="mt-1 text-[11px] text-[var(--color-muted)]">{item.detail} · {tone.text}</div>
            </div>
          );
        })}
      </div>
    </details>
  );
}