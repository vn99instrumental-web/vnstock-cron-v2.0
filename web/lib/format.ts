// Helper format số/ngày cho bảng data-dense. Nhãn tiếng Việt.

export function fmtNum(v: unknown, digits = 2): string {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("vi-VN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPct(v: unknown, digits = 2): string {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!Number.isFinite(n)) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(digits) + "%";
}

/** Màu theo dấu (dương xanh lá, âm đỏ). */
export function signClass(v: unknown): string {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!Number.isFinite(n) || n === 0) return "text-[var(--color-muted)]";
  return n > 0 ? "text-[var(--color-buy)]" : "text-[var(--color-sell)]";
}

/** "2026-09-03T09:27:00+07:00" → "09:27" ; "2026-09-03" giữ nguyên. */
export function snapHM(ts: unknown): string {
  const s = String(ts ?? "");
  const m = s.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : s;
}
