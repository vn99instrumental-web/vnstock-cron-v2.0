export function MissingDataValue({ label = "Chưa có dữ liệu", title }: { label?: string; title?: string }) {
  return (
    <span
      className="inline-flex items-center rounded border border-amber-500/50 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300"
      title={title ?? label}
    >
      {label}
    </span>
  );
}

export function MissingDataNotice({ items, className = "" }: { items: string[]; className?: string }) {
  if (!items.length) return null;
  return (
    <div role="status" className={`mb-3 rounded-lg border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-200 ${className}`}>
      <span className="font-semibold">Dữ liệu chưa có:</span>{" "}{items.join(" · ")}
    </div>
  );
}
