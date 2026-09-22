"use client";

import { useMemo, useState } from "react";
import { FACTOR_GROUPS, signalName } from "@/lib/interpret";

export interface OfficialICRow {
  factor: string;
  horizon: number;
  ic: number | null;
  n: number | null;
}
export interface MargRow {
  indicator: string;
  factor: string | null;
  horizon: number;
  coef: number | null;
  tstat: number | null;
  univar_ic: number | null;
  n: number | null;
}

const HORIZONS = [1, 3, 5, 10];
const FACTOR_ROWS = [
  { key: "score_trade", label: "Điểm tổng", members: [] as string[] },
  ...FACTOR_GROUPS.map((g) => ({ key: g.key, label: g.label, members: g.members })),
];

/** Màu IC official (đậm theo |IC|, chuẩn hoá ±0.2). */
function icCell(ic: number | null): { bg: string; fg: string } {
  if (ic === null || !Number.isFinite(ic)) return { bg: "transparent", fg: "var(--color-muted)" };
  const a = Math.min(1, Math.abs(ic) / 0.2) * 0.8;
  return { bg: ic >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`, fg: a > 0.45 ? "#fff" : "var(--color-ink)" };
}
/** Màu hệ số biên (đậm theo |coef|, chuẩn hoá ±0.3). */
function coefCell(x: number | null): { bg: string; fg: string } {
  if (x === null || !Number.isFinite(x)) return { bg: "transparent", fg: "var(--color-muted)" };
  const a = Math.min(1, Math.abs(x) / 0.3) * 0.8;
  return { bg: x >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`, fg: a > 0.45 ? "#fff" : "var(--color-ink)" };
}
function verdict(coef: number | null, t: number | null, uic: number | null): string {
  if (coef === null || t === null) return "";
  const sig = Math.abs(t) >= 2;
  if (sig && coef > 0) return "GIỮ/tăng";
  if (sig && coef < 0) return "GIẢM/đảo";
  if (uic !== null && Math.abs(uic) >= 0.08 && Math.abs(coef) < 0.06) return "trùng lặp";
  return "yếu";
}

/**
 * Bảng IC official theo NHÂN TỐ (heatmap × horizon) + BUNG ra chỉ báo con kèm
 * ĐÓNG GÓP BIÊN (hồi quy đa biến) — hợp nhất 2 bảng thành 1 view / version.
 */
export function FactorICTable({
  version, curVer, official, marginal,
}: {
  version: string;
  curVer: string | null;
  official: OfficialICRow[];
  marginal: MargRow[];
}) {
  // official: factor → horizon → {ic,n}
  const offMap = useMemo(() => {
    const m = new Map<string, Map<number, { ic: number | null; n: number | null }>>();
    for (const r of official) {
      if (!m.has(r.factor)) m.set(r.factor, new Map());
      m.get(r.factor)!.set(r.horizon, { ic: r.ic, n: r.n });
    }
    return m;
  }, [official]);
  // marginal: indicator → horizon → row
  const margMap = useMemo(() => {
    const m = new Map<string, Map<number, MargRow>>();
    for (const r of marginal) {
      if (r.indicator === "_model_r2") continue;
      if (!m.has(r.indicator)) m.set(r.indicator, new Map());
      m.get(r.indicator)!.set(r.horizon, r);
    }
    return m;
  }, [marginal]);
  const r2 = useMemo(() => {
    const row = marginal.find((r) => r.indicator === "_model_r2" && r.horizon === 5);
    return row?.coef ?? null;
  }, [marginal]);

  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (k: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k); else n.add(k);
      return n;
    });

  // chỉ hiện factor row nếu có IC official HOẶC có ≥1 chỉ báo con có marginal.
  const rows = FACTOR_ROWS.map((f) => {
    const members = f.members.filter((k) => margMap.has(k));
    const hasOff = offMap.has(f.key);
    return { ...f, members, hasOff };
  }).filter((f) => f.hasOff || f.members.length);

  if (!rows.length) return null;

  return (
    <div className="mb-6">
      <h2 className="mb-2 flex flex-wrap items-center gap-2 font-mono text-sm font-semibold">
        scoring {version}
        {version === curVer ? (
          <span className="rounded bg-[var(--color-accent)] px-1.5 py-0.5 text-[10px] font-semibold text-white">hiện tại</span>
        ) : null}
        {r2 != null ? (
          <span className="text-[11px] font-normal text-[var(--color-muted)]">· hồi quy đa biến R²(5d) = {(r2 * 100).toFixed(1)}%</span>
        ) : null}
      </h2>
      <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="bg-black/[0.03] text-xs text-[var(--color-muted)] dark:bg-white/[0.03]">
            <tr>
              <th className="px-3 py-2 text-left">Factor / chỉ báo</th>
              {HORIZONS.map((h) => <th key={h} className="px-3 py-2 text-center">{h}d</th>)}
              <th className="px-2 py-2 text-center">Kết luận</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => {
              const expandable = f.members.length > 0;
              const isOpen = open.has(f.key);
              return (
                <FactorBlock
                  key={f.key}
                  fkey={f.key}
                  label={f.label}
                  members={f.members}
                  expandable={expandable}
                  isOpen={isOpen}
                  onToggle={() => toggle(f.key)}
                  offMap={offMap}
                  margMap={margMap}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FactorBlock({
  fkey, label, members, expandable, isOpen, onToggle, offMap, margMap,
}: {
  fkey: string;
  label: string;
  members: string[];
  expandable: boolean;
  isOpen: boolean;
  onToggle: () => void;
  offMap: Map<string, Map<number, { ic: number | null; n: number | null }>>;
  margMap: Map<string, Map<number, MargRow>>;
}) {
  const off = offMap.get(fkey);
  return (
    <>
      <tr
        className={`border-t border-[var(--color-border)] ${expandable ? "cursor-pointer hover:bg-black/[0.02] dark:hover:bg-white/[0.03]" : ""}`}
        onClick={expandable ? onToggle : undefined}
      >
        <td className="px-3 py-2 font-medium">
          {expandable ? (
            <span className="mr-1 inline-block w-3 text-[var(--color-muted)]">{isOpen ? "▾" : "▸"}</span>
          ) : (
            <span className="mr-1 inline-block w-3" />
          )}
          {label}
          {expandable ? <span className="ml-1 text-[11px] font-normal text-[var(--color-muted)]">({members.length} chỉ báo)</span> : null}
        </td>
        {HORIZONS.map((h) => {
          const c = off?.get(h);
          const ic = c?.ic ?? null;
          const { bg, fg } = icCell(ic);
          return (
            <td key={h} className="tabular px-3 py-2 text-center" style={{ backgroundColor: bg, color: fg }}
              title={c ? `IC official ${(ic != null && ic >= 0 ? "+" : "") + (ic == null ? "—" : ic.toFixed(3))} · n=${c.n ?? "?"} (evaluator, chuẩn theo-ngày)` : "chưa có IC official"}>
              {ic == null ? "—" : (ic >= 0 ? "+" : "") + ic.toFixed(3)}
            </td>
          );
        })}
        <td className="px-2 py-2 text-center text-[11px] text-[var(--color-muted)]">{expandable ? (isOpen ? "" : "xem") : ""}</td>
      </tr>
      {isOpen
        ? members.map((ind) => {
            const mm = margMap.get(ind);
            const v5 = mm?.get(5);
            const vd = verdict(v5?.coef ?? null, v5?.tstat ?? null, v5?.univar_ic ?? null);
            const vdCls =
              vd === "GIỮ/tăng" ? "text-[var(--color-buy)] font-semibold"
              : vd === "GIẢM/đảo" ? "text-[var(--color-sell)] font-semibold"
              : "text-[var(--color-muted)]";
            return (
              <tr key={ind} className="border-t border-[var(--color-border)]/60 bg-black/[0.015] dark:bg-white/[0.02]">
                <td className="py-1.5 pl-8 pr-3 text-[13px]" title={ind}>
                  <span className="text-[var(--color-muted)]">└ </span>{signalName(ind)}
                </td>
                {HORIZONS.map((h) => {
                  const r = mm?.get(h);
                  const coef = r?.coef ?? null;
                  const sig = r?.tstat != null && Math.abs(r.tstat) >= 2;
                  const { bg, fg } = coefCell(coef);
                  const title = r
                    ? `${signalName(ind)} · ${h}d\nĐóng góp biên (coef chuẩn hoá) = ${(coef != null && coef >= 0 ? "+" : "") + (coef == null ? "—" : coef.toFixed(3))}` +
                      `\nt-stat = ${r.tstat ?? "—"}${sig ? " (có ý nghĩa)" : " (không ý nghĩa)"}` +
                      `\nIC đơn biến = ${r.univar_ic ?? "—"}` +
                      `\n→ ${verdict(coef, r.tstat, r.univar_ic)}`
                    : "chưa có dữ liệu";
                  return (
                    <td key={h} className={`tabular px-3 py-1.5 text-center text-[12px] ${sig ? "font-semibold" : ""}`}
                      style={{ backgroundColor: bg, color: fg }} title={title}>
                      {coef == null ? "—" : (coef >= 0 ? "+" : "") + coef.toFixed(2)}
                    </td>
                  );
                })}
                <td className={`px-2 py-1.5 text-center text-[11px] ${vdCls}`}>{vd}</td>
              </tr>
            );
          })
        : null}
    </>
  );
}
