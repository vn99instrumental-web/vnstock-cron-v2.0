"use client";

import { useMemo, useState } from "react";
import { signalName } from "@/lib/interpret";

export interface MarginalRow {
  version: string;
  indicator: string;
  factor: string | null;
  horizon: number;
  coef: number | null;
  tstat: number | null;
  univar_ic: number | null;
  n: number | null;
}

const HZ = [1, 3, 5, 10];
const FACTOR_VN: Record<string, string> = {
  mean_reversion: "Hồi quy TB",
  breakout: "Bứt phá",
  flow: "Dòng tiền",
  fundamental: "Cơ bản",
  growth: "Tăng trưởng",
  context: "Bối cảnh",
};

/** Màu diverging cho hệ số (đậm theo |x|, chuẩn hoá ±0.3). */
function coefColor(x: number | null): { bg: string; fg: string } {
  if (x === null || !Number.isFinite(x)) return { bg: "transparent", fg: "var(--color-muted)" };
  const a = Math.min(1, Math.abs(x) / 0.3) * 0.8;
  const bg = x >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`;
  return { bg, fg: a > 0.45 ? "#fff" : "var(--color-ink)" };
}

/** Kết luận cho combine: dựa hệ số biên + độ tin (t) + so với IC đơn biến. */
function verdict(coef: number | null, t: number | null, uic: number | null): { label: string; cls: string } {
  if (coef === null || t === null) return { label: "—", cls: "text-[var(--color-muted)]" };
  const sig = Math.abs(t) >= 2;
  if (sig && coef > 0) return { label: "GIỮ / tăng", cls: "text-[var(--color-buy)] font-semibold" };
  if (sig && coef < 0) return { label: "GIẢM / đảo", cls: "text-[var(--color-sell)] font-semibold" };
  // không ý nghĩa: nếu IC đơn biến mạnh mà biên ~0 → bị trùng lặp
  if (uic !== null && Math.abs(uic) >= 0.08 && Math.abs(coef) < 0.06)
    return { label: "trùng lặp", cls: "text-[var(--color-muted)] italic" };
  return { label: "yếu", cls: "text-[var(--color-muted)]" };
}

/**
 * Bảng đóng góp BIÊN của chỉ báo con (hồi quy đa biến) cho 1 version.
 * Chọn version + horizon. Sort theo hệ số biên (đóng góp độc lập mạnh nhất lên đầu).
 */
export function MarginalTable({ rows, curVer }: { rows: MarginalRow[]; curVer: string | null }) {
  const versions = useMemo(() => {
    const vs = [...new Set(rows.map((r) => r.version))];
    vs.sort(
      (a, b) =>
        (b === curVer ? 1 : 0) - (a === curVer ? 1 : 0) ||
        b.localeCompare(a, undefined, { numeric: true }),
    );
    return vs;
  }, [rows, curVer]);

  const [ver, setVer] = useState(versions[0] ?? "");
  const [hz, setHz] = useState(5);
  const activeVer = versions.includes(ver) ? ver : versions[0] ?? "";

  const { list, r2, n } = useMemo(() => {
    const sub = rows.filter((r) => r.version === activeVer && r.horizon === hz);
    const model = sub.find((r) => r.indicator === "_model_r2");
    const list = sub
      .filter((r) => r.indicator !== "_model_r2")
      .sort((a, b) => (b.coef ?? -99) - (a.coef ?? -99));
    return { list, r2: model?.coef ?? null, n: model?.n ?? null };
  }, [rows, activeVer, hz]);

  if (!versions.length) return <p className="text-xs text-[var(--color-muted)]">Chưa đủ mẫu để hồi quy.</p>;

  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
        <div className="flex items-center gap-1">
          <span className="text-[var(--color-muted)]">Version:</span>
          {versions.map((v) => (
            <button
              key={v}
              onClick={() => setVer(v)}
              className={`min-h-[26px] rounded-md border px-2 py-0.5 font-mono ${
                v === activeVer
                  ? "border-[var(--color-accent)] bg-[var(--color-accent)] font-semibold text-white"
                  : "border-[var(--color-border)] text-[var(--color-muted)]"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[var(--color-muted)]">Khung:</span>
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
      </div>

      <div className="mb-1.5 text-[11px] text-[var(--color-muted)]">
        Mô hình {activeVer} @ {hz}d giải thích <b className="text-[var(--color-ink)]">R² = {r2 != null ? (r2 * 100).toFixed(1) + "%" : "—"}</b>{" "}
        biến thiên lợi nhuận (cross-sectional) · n = {n ?? "?"} quan sát.
      </div>

      <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="bg-black/[0.03] text-xs text-[var(--color-muted)] dark:bg-white/[0.03]">
            <tr>
              <th className="px-2.5 py-2 text-left">Chỉ báo</th>
              <th className="px-2 py-2 text-left">Nhóm</th>
              <th className="cursor-help px-2 py-2 text-center" title="IC đơn biến (Spearman) — tương quan thô, chưa khử trùng lặp">IC đơn</th>
              <th className="cursor-help px-2 py-2 text-center" title="Hệ số hồi quy đa biến chuẩn hoá = đóng góp RIÊNG khi đã kiểm soát các chỉ báo khác">Biên</th>
              <th className="cursor-help px-2 py-2 text-center" title="t-stat: |t|≥2 ~ có ý nghĩa thống kê">t</th>
              <th className="px-2 py-2 text-left">Kết luận combine</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r) => {
              const { bg, fg } = coefColor(r.coef);
              const v = verdict(r.coef, r.tstat, r.univar_ic);
              const sig = r.tstat !== null && Math.abs(r.tstat) >= 2;
              return (
                <tr key={r.indicator} className="border-t border-[var(--color-border)]">
                  <td className="px-2.5 py-1.5 font-medium" title={r.indicator}>{signalName(r.indicator)}</td>
                  <td className="px-2 py-1.5 text-[12px] text-[var(--color-muted)]">{r.factor ? FACTOR_VN[r.factor] ?? r.factor : "—"}</td>
                  <td className="tabular px-2 py-1.5 text-center text-[12px] text-[var(--color-muted)]">
                    {r.univar_ic == null ? "—" : (r.univar_ic >= 0 ? "+" : "") + r.univar_ic.toFixed(2)}
                  </td>
                  <td className="tabular px-2 py-1.5 text-center" style={{ backgroundColor: bg, color: fg }}>
                    {r.coef == null ? "—" : (r.coef >= 0 ? "+" : "") + r.coef.toFixed(2)}
                  </td>
                  <td className={`tabular px-2 py-1.5 text-center text-[12px] ${sig ? "font-semibold" : "text-[var(--color-muted)]"}`}>
                    {r.tstat == null ? "—" : (r.tstat >= 0 ? "+" : "") + r.tstat.toFixed(1)}
                  </td>
                  <td className={`px-2 py-1.5 text-[12px] ${v.cls}`}>{v.label}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-[var(--color-muted)]">
        <b>Biên</b> = đóng góp độc lập sau khi khử trùng lặp với chỉ báo khác. So với <b>IC đơn</b>: IC đơn cao mà biên ~0 ⇒
        tín hiệu bị chỉ báo khác &ldquo;nuốt&rdquo; (trùng lặp). Ưu tiên giữ chỉ báo <b>biên mạnh + |t|≥2</b>. Ước lượng
        pooled trong version, tham chiếu — không phải IC chính thức.
      </p>
    </div>
  );
}
