"use client";

import { useMemo, useState } from "react";

export interface FactorVerRow {
  version: string;
  factor: string;
  horizon: number;
  ic: number | null;
  n: number;
}

const FACTORS: { key: string; short: string; full: string }[] = [
  { key: "score_trade", short: "Tổng", full: "score_trade — điểm tổng (chất lượng tín hiệu chung)" },
  { key: "mean_reversion", short: "MeanRev", full: "mean_reversion — hồi quy về trung bình (quá bán/quá bán sâu)" },
  { key: "breakout", short: "Breakout", full: "breakout — bứt phá/xu hướng (dist 52w, trend, volume)" },
  { key: "flow", short: "Flow", full: "flow — dòng tiền (khối ngoại, order-flow, tự doanh, insider)" },
  { key: "fundamental", short: "Fund", full: "fundamental — cơ bản (định giá, dòng tiền DN)" },
  { key: "growth", short: "Growth", full: "growth — tăng trưởng" },
  { key: "context", short: "Context", full: "context — bối cảnh thị trường chung" },
];

const HZ = [1, 3, 5, 10];

/** Màu diverging: dương xanh, âm đỏ, đậm theo |IC| (chuẩn hoá ±0.2). */
function cell(ic: number | null): { bg: string; fg: string } {
  if (ic === null || !Number.isFinite(ic)) return { bg: "transparent", fg: "var(--color-muted)" };
  const a = Math.min(1, Math.abs(ic) / 0.2) * 0.8;
  const bg = ic >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`;
  return { bg, fg: a > 0.45 ? "#fff" : "var(--color-ink)" };
}
function strength(ic: number | null): string {
  if (ic === null || !Number.isFinite(ic)) return "chưa có dữ liệu";
  const a = Math.abs(ic);
  return a < 0.02 ? "gần như không dự báo" : a < 0.05 ? "có tín hiệu" : a < 0.1 ? "tốt" : "rất mạnh";
}

/**
 * Ma trận IC nhân tố × version (mọi version) — ước lượng pooled, tham chiếu.
 * Hàng = version, cột = nhân tố. Đổi horizon để so ngắn/dài hạn. Dùng để soi
 * factor nào dương ổn định ở nhiều version → combine cho version mới.
 */
export function FactorVerMatrix({
  rows,
  curVer,
  minN = 30,
}: {
  rows: FactorVerRow[];
  curVer: string | null;
  minN?: number;
}) {
  const [hz, setHz] = useState(5);

  // index: version → factor → {ic, n} tại horizon đang chọn
  const { versions, idx } = useMemo(() => {
    const m = new Map<string, Map<string, { ic: number | null; n: number }>>();
    for (const r of rows) {
      if (r.horizon !== hz) continue;
      if (!m.has(r.version)) m.set(r.version, new Map());
      m.get(r.version)!.set(r.factor, { ic: r.ic, n: r.n });
    }
    // chỉ giữ version có score_trade đủ n
    const vers = [...m.keys()].filter((v) => (m.get(v)!.get("score_trade")?.n ?? 0) >= minN);
    vers.sort(
      (a, b) =>
        (b === curVer ? 1 : 0) - (a === curVer ? 1 : 0) ||
        b.localeCompare(a, undefined, { numeric: true }),
    );
    return { versions: vers, idx: m };
  }, [rows, hz, minN, curVer]);

  if (!versions.length) return <p className="text-xs text-[var(--color-muted)]">Chưa đủ dữ liệu.</p>;

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[12px]">
        <span className="text-[var(--color-muted)]">Khung lợi nhuận:</span>
        {HZ.map((h) => (
          <button
            key={h}
            onClick={() => setHz(h)}
            className={`min-h-[26px] rounded-md border px-2 py-0.5 ${
              h === hz
                ? "border-[var(--color-accent)] bg-[var(--color-accent)] font-semibold text-white"
                : "border-[var(--color-border)] text-[var(--color-muted)]"
            }`}
          >
            {h}d
          </button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="bg-black/[0.03] text-xs text-[var(--color-muted)] dark:bg-white/[0.03]">
            <tr>
              <th className="sticky left-0 z-10 bg-[var(--color-surface)] px-2.5 py-2 text-left">Version</th>
              {FACTORS.map((f) => (
                <th key={f.key} className="cursor-help px-2 py-2 text-center" title={f.full}>
                  {f.short}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v} className="border-t border-[var(--color-border)]">
                <td
                  className={`sticky left-0 z-10 bg-[var(--color-surface)] px-2.5 py-2 font-mono text-[12px] font-medium ${
                    v === curVer ? "text-[var(--color-accent)]" : ""
                  }`}
                >
                  {v}
                  {v === curVer ? " ●" : ""}
                </td>
                {FACTORS.map((f) => {
                  const c = idx.get(v)?.get(f.key);
                  const ic = c?.ic ?? null;
                  const { bg, fg } = cell(ic);
                  const title =
                    `${v} · ${f.short} · sau ${hz} phiên\n` +
                    (ic === null
                      ? "chưa đủ dữ liệu"
                      : `IC ${(ic >= 0 ? "+" : "") + ic.toFixed(3)} — ${strength(ic)}` +
                        (ic > 0 ? " (thuận)" : ic < 0 ? " (nghịch)" : "")) +
                    `\nn = ${c?.n ?? "?"} quan sát (gộp toàn kỳ)`;
                  return (
                    <td
                      key={f.key}
                      className="tabular cursor-help px-2 py-2 text-center text-[13px]"
                      style={{ backgroundColor: bg, color: fg }}
                      title={title}
                    >
                      {ic === null ? "—" : (ic >= 0 ? "+" : "") + ic.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-[var(--color-muted)]">
        ● = version đang chạy. Xanh = factor dự báo thuận, đỏ = nghịch (nên giảm/đảo trọng số). Rê chuột xem n.
        Ước lượng pooled — version n nhỏ (cũ) nhiễu cao, chỉ tham chiếu.
      </p>
    </div>
  );
}
