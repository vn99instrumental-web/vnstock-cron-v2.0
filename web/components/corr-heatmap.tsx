"use client";

import { varName } from "@/lib/interpret";

export interface FactorPair {
  fa: string;
  fb: string;
  corr: number | string | null;
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

/** Màu diverging cho hệ số tương quan [-1,1]: xanh dương dương, đỏ âm, nhạt gần 0. */
function cellColor(v: number): string {
  const a = Math.min(1, Math.abs(v));
  if (v >= 0) return `rgba(37, 99, 235, ${(0.12 + 0.78 * a).toFixed(3)})`; // xanh dương
  return `rgba(220, 38, 38, ${(0.12 + 0.78 * a).toFixed(3)})`; // đỏ
}

/**
 * Ma trận tương quan biến×biến. `pairs` chỉ có nửa trên (fa<fb) → tự soi gương.
 * Nhãn hàng = tên biến; nhãn cột = số thứ tự (legend bên dưới) cho gọn.
 */
export function CorrHeatmap({ pairs, factors }: { pairs: FactorPair[]; factors: string[] }) {
  const map = new Map<string, number>();
  for (const p of pairs) {
    const v = num(p.corr);
    if (v != null) map.set(`${p.fa}|${p.fb}`, v);
  }
  const get = (a: string, b: string): number | null => {
    if (a === b) return 1;
    const k = a < b ? `${a}|${b}` : `${b}|${a}`;
    return map.get(k) ?? null;
  };

  if (factors.length < 2) {
    return <div className="py-3 text-center text-[11px] text-[var(--color-muted)]">Cần ≥ 2 biến để vẽ ma trận.</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-[10px]">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-[var(--color-surface)] px-1 py-0.5" />
            {factors.map((_, j) => (
              <th key={j} className="px-0 py-0.5 text-center font-normal text-[var(--color-muted)]" style={{ minWidth: 24 }}>{j + 1}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {factors.map((fa, i) => (
            <tr key={fa}>
              <td className="sticky left-0 z-10 whitespace-nowrap bg-[var(--color-surface)] py-0.5 pr-2 text-right" title={fa}>
                <span className="text-[var(--color-muted)]">{i + 1}.</span> {varName(fa)}
              </td>
              {factors.map((fb, j) => {
                const v = get(fa, fb);
                const diag = i === j;
                return (
                  <td
                    key={fb}
                    className="text-center tabular"
                    title={`${varName(fa)} × ${varName(fb)} = ${v != null ? v.toFixed(2) : "—"}`}
                    style={{
                      background: diag ? "var(--color-border)" : v != null ? cellColor(v) : "transparent",
                      width: 24, height: 22,
                      color: v != null && Math.abs(v) > 0.55 ? "#fff" : "var(--color-muted)",
                      border: "1px solid var(--color-surface)",
                    }}
                  >
                    {diag ? "" : v != null && Math.abs(v) >= 0.5 ? Math.round(v * 100) : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {/* Chú giải gradient */}
      <div className="mt-2 flex items-center gap-2 text-[10px] text-[var(--color-muted)]">
        <span>−1</span>
        <span className="h-2.5 w-28 rounded" style={{ background: "linear-gradient(90deg, rgba(220,38,38,0.9), rgba(220,38,38,0.12), rgba(37,99,235,0.12), rgba(37,99,235,0.9))" }} />
        <span>+1</span>
        <span className="ml-1">ngược chiều ← → cùng chiều · số = hệ số ×100 (hiện khi |r|≥0.5)</span>
      </div>
      <p className="mt-1 text-[10px] italic text-[var(--color-muted)]">
        Ô đậm ngoài đường chéo = 2 biến gần trùng nhau (đa cộng tuyến) → cân nhắc bỏ bớt 1 khi chỉnh trọng số. Cột đánh số theo hàng cùng tên.
      </p>
    </div>
  );
}
