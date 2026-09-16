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

/**
 * Giờ theo giờ Việt Nam (GMT+7). snap_time/started_at là timestamptz (UTC),
 * nên phải quy đổi timezone — KHÔNG cắt chuỗi thô (sẽ ra giờ UTC).
 * "2026-09-16T07:13:00+00:00" → "14:13".
 */
export function hmVN(ts: unknown): string {
  const raw = String(ts ?? "");
  if (!raw) return "—";
  // Postgres text "YYYY-MM-DD HH:MM:SS+00" → ISO có 'T' để Date parse chắc chắn.
  const s = !raw.includes("T") && raw.includes(" ") ? raw.replace(" ", "T") : raw;
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return snapHM(ts); // fallback an toàn
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

/** VND ròng → "+1.7 tỷ" / "-301 tr" (khối ngoại phiên). */
export function fmtBil(v: unknown): string {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!Number.isFinite(n)) return "—";
  const b = n / 1e9;
  if (Math.abs(b) >= 0.1) return (b >= 0 ? "+" : "") + b.toFixed(1) + " tỷ";
  return (n >= 0 ? "+" : "") + (n / 1e6).toFixed(0) + " tr";
}
