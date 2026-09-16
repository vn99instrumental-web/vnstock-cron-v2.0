"use client";

import { useMemo, useState } from "react";
import { DecisionBadge } from "@/components/ui";
import { fmtNum, fmtPct, signClass } from "@/lib/format";
import { signalName, CONFIDENCE_LABEL } from "@/lib/interpret";

export interface SignalResult {
  pred_id: string;
  symbol: string;
  signal_date: string;
  snap_time: string | null;
  decision: string | null;
  confidence: string | null;
  t0_close: number | string | null;
  ret_1d: number | string | null;
  ret_5d: number | string | null;
  ret_10d: number | string | null;
  mfe_pct: number | string | null;
  mae_pct: number | string | null;
  own_entry: number | string | null;
  own_tp1: number | string | null;
  own_tp2: number | string | null;
  own_stop: number | string | null;
  std_outcome: string | null;   // +6% / −4%
  std_days: number | string | null;
  std3_outcome: string | null;  // +3% / −3%
  own_outcome: string | null;   // tp1 / tp2 / sl / open (null trước T9)
  own_days: number | string | null;
}

export interface FactorCorr {
  factor: string;
  n: number;
  corr_ret5: number | string | null;
  corr_win: number | string | null;
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

const BUY = "var(--color-buy)";
const SELL = "var(--color-sell)";
const MUTED = "var(--color-muted)";

/** Nhãn + màu cho một kết quả: tp/tp1/tp2, sl, open, hoặc null (chờ chín). */
function outcomeMeta(o: string | null): { label: string; color: string; kind: "tp" | "sl" | "open" | "wait" } {
  if (o == null) return { label: "chờ chín", color: MUTED, kind: "wait" };
  if (o.startsWith("tp")) return { label: o === "tp2" ? "chạm TP2" : o === "tp1" ? "chạm TP1" : "chạm TP", color: BUY, kind: "tp" };
  if (o === "sl") return { label: "chạm SL", color: SELL, kind: "sl" };
  return { label: "chưa chạm", color: MUTED, kind: "open" };
}

function OutcomeDot({ o, title }: { o: string | null; title?: string }) {
  const m = outcomeMeta(o);
  return (
    <span
      title={title}
      aria-label={m.label}
      style={{ background: m.color }}
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
    />
  );
}

function ConfMini({ conf }: { conf: string | null }) {
  const c = CONFIDENCE_LABEL[String(conf ?? "").toUpperCase()];
  if (!c) return <span className="text-[var(--color-muted)]">—</span>;
  return <span style={{ color: c.color }}>{c.text}</span>;
}

type TargetKey = "std3_outcome" | "std_outcome";
const TARGETS: { key: TargetKey; label: string; days: keyof SignalResult }[] = [
  { key: "std3_outcome", label: "Mục tiêu +3% / cắt −3%", days: "std_days" },
  { key: "std_outcome", label: "Mục tiêu +6% / cắt −4%", days: "std_days" },
];

/** Thanh xếp chồng tỷ lệ TP / chưa chạm / SL. */
function HitBar({ tp, open, sl }: { tp: number; open: number; sl: number }) {
  const total = tp + open + sl || 1;
  const seg = (n: number, color: string, label: string) =>
    n > 0 ? (
      <div style={{ width: `${(100 * n) / total}%`, background: color }} className="h-full" title={`${label}: ${n} (${((100 * n) / total).toFixed(0)}%)`} />
    ) : null;
  return (
    <div className="flex h-4 w-full overflow-hidden rounded border border-[var(--color-border)]">
      {seg(tp, BUY, "chạm TP")}
      {seg(open, "var(--color-border)", "chưa chạm")}
      {seg(sl, SELL, "chạm SL")}
    </div>
  );
}

export function AnalysisBoard({ results, corr }: { results: SignalResult[]; corr: FactorCorr[] }) {
  const [tab, setTab] = useState<"overall" | "symbol">("overall");
  const [target, setTarget] = useState<TargetKey>("std3_outcome");
  const [corrMetric, setCorrMetric] = useState<"corr_ret5" | "corr_win">("corr_ret5");
  const symbols = useMemo(
    () => [...new Set(results.map((r) => r.symbol))].sort(),
    [results],
  );
  const [sym, setSym] = useState<string>(symbols[0] ?? "");

  // Khung dữ liệu (độ tươi, phạm vi).
  const meta = useMemo(() => {
    const dates = results.map((r) => r.signal_date).sort();
    const hasOwn = results.some((r) => r.own_outcome != null);
    return { n: results.length, nSym: symbols.length, d0: dates[0], d1: dates[dates.length - 1], hasOwn };
  }, [results, symbols]);

  // Đếm kết quả cho target đang chọn (tổng + theo quyết định).
  const agg = useMemo(() => {
    const tally = (rows: SignalResult[]) => {
      let tp = 0, sl = 0, open = 0;
      for (const r of rows) {
        const o = r[target] as string | null;
        if (o === "tp") tp++;
        else if (o === "sl") sl++;
        else open++;
      }
      return { tp, sl, open, n: rows.length };
    };
    return {
      all: tally(results),
      buy: tally(results.filter((r) => r.decision === "BUY")),
      sbuy: tally(results.filter((r) => r.decision === "STRONG BUY")),
    };
  }, [results, target]);

  const corrSorted = useMemo(
    () =>
      [...corr]
        .map((c) => ({ ...c, v: num(c[corrMetric]) }))
        .filter((c) => c.v != null)
        .sort((a, b) => Math.abs(b.v!) - Math.abs(a.v!)),
    [corr, corrMetric],
  );
  const corrMax = useMemo(
    () => Math.max(0.2, ...corrSorted.map((c) => Math.abs(c.v!))),
    [corrSorted],
  );

  const symRows = useMemo(
    () => results.filter((r) => r.symbol === sym).sort((a, b) => a.signal_date.localeCompare(b.signal_date)),
    [results, sym],
  );

  const TabBtn = ({ k, label }: { k: "overall" | "symbol"; label: string }) => (
    <button
      onClick={() => setTab(k)}
      className={`rounded-md px-3 py-1.5 text-sm font-medium ${
        tab === k ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-muted)] hover:bg-black/5 dark:hover:bg-white/5"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Cảnh báo phạm vi + phương pháp (trung thực) */}
      <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[11px] text-[var(--color-muted)]">
        <b className="text-[var(--color-ink)]">{meta.n}</b> tín hiệu chín · <b className="text-[var(--color-ink)]">{meta.nSym}</b> mã · {meta.d0} → {meta.d1}.
        Kết quả “chạm TP/SL” xác định bằng <b className="text-[var(--color-ink)]">đường giá nến thật</b> (chạm cái nào trước, theo ngày).
        {" "}Tương quan biến là <b className="text-[var(--color-ink)]">khám phá</b> (mẫu nhỏ, 1 tháng) — <i>không phải IC chính thức</i> (IC từ pipeline Python ở tab Chất lượng).
        {!meta.hasOwn ? (
          <span className="text-[var(--color-sell)]"> · TP/SL RIÊNG của model chỉ lưu từ T9/2026 nên chưa mã nào đủ chín — dùng mục tiêu chuẩn ±% bên dưới; số “own” sẽ tự đầy từ cuối T9.</span>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        <TabBtn k="overall" label="Góc tổng thể" />
        <TabBtn k="symbol" label="Từng mã" />
      </div>

      {tab === "overall" ? (
        <div className="flex flex-col gap-4">
          {/* Chọn mục tiêu */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-[var(--color-muted)]">Mục tiêu chốt/cắt:</span>
            {TARGETS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTarget(t.key)}
                className={`rounded border px-2 py-1 ${target === t.key ? "border-[var(--color-accent)] text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-muted)]"}`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Tỷ lệ chạm TP/SL — tổng + theo quyết định */}
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
            <h3 className="mb-2 text-sm font-semibold">Tỷ lệ chạm mục tiêu (đi theo nến thật, cửa sổ ~10 phiên)</h3>
            <div className="flex flex-col gap-2.5">
              {[
                { label: "Tất cả BUY", a: agg.all },
                { label: "BUY", a: agg.buy },
                { label: "STRONG BUY", a: agg.sbuy },
              ].filter((r) => r.a.n > 0).map((r) => {
                const pct = (x: number) => (r.a.n ? Math.round((100 * x) / r.a.n) : 0);
                return (
                  <div key={r.label} className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-xs font-medium">{r.label} <span className="text-[10px] text-[var(--color-muted)]">n={r.a.n}</span></span>
                    <div className="flex-1"><HitBar tp={r.a.tp} open={r.a.open} sl={r.a.sl} /></div>
                    <span className="tabular w-40 shrink-0 text-right text-[11px]">
                      <b style={{ color: BUY }}>TP {pct(r.a.tp)}%</b> · <span style={{ color: MUTED }}>chờ {pct(r.a.open)}%</span> · <b style={{ color: SELL }}>SL {pct(r.a.sl)}%</b>
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="mt-2 text-[10px] italic text-[var(--color-muted)]">
              Quy ước bảo thủ: nếu 1 ngày vừa chạm TP vừa chạm SL (không rõ thứ tự trong phiên) → tính SL trước.
            </p>
          </div>

          {/* Tương quan biến đầu vào */}
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold">Biến đầu vào nào liên quan kết quả?</h3>
              <div className="ml-auto flex items-center gap-1 text-[11px]">
                <button onClick={() => setCorrMetric("corr_ret5")} className={`rounded border px-2 py-0.5 ${corrMetric === "corr_ret5" ? "border-[var(--color-accent)] text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-muted)]"}`}>vs lãi 5 phiên</button>
                <button onClick={() => setCorrMetric("corr_win")} className={`rounded border px-2 py-0.5 ${corrMetric === "corr_win" ? "border-[var(--color-accent)] text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-muted)]"}`}>vs chạm TP</button>
              </div>
            </div>
            <div className="flex flex-col gap-1">
              {corrSorted.map((c) => {
                const v = c.v!;
                const w = Math.min(50, (Math.abs(v) / corrMax) * 50);
                const color = v >= 0 ? BUY : SELL;
                return (
                  <div key={c.factor} className="flex items-center gap-2 text-[11px]">
                    <span className="w-44 shrink-0 truncate" title={c.factor}>{signalName(c.factor)}</span>
                    <div className="relative h-3 flex-1 rounded bg-black/5 dark:bg-white/10">
                      <div className="absolute left-1/2 top-0 h-3 w-px bg-[var(--color-border)]" />
                      <div className="absolute top-0 h-3 rounded" style={{ backgroundColor: color, left: v >= 0 ? "50%" : `${50 - w}%`, width: `${w}%` }} />
                    </div>
                    <span className="tabular w-12 shrink-0 text-right" style={{ color }}>{v >= 0 ? "+" : ""}{v.toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
            <p className="mt-2 text-[10px] italic text-[var(--color-muted)]">
              Xanh = biến càng cao thì kết quả càng tốt; đỏ = càng cao càng xấu. Độ dài = độ mạnh liên quan (|hệ số|).
              Đây là gợi ý để soi lại trọng số, <b>không</b> phải kết luận nhân quả (mẫu 1 tháng).
            </p>
          </div>
        </div>
      ) : (
        /* ===== TỪNG MÃ ===== */
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-[var(--color-muted)]">Chọn mã:</span>
            <select value={sym} onChange={(e) => setSym(e.target.value)} className="rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-sm">
              {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <span className="text-[var(--color-muted)]">{symRows.length} tín hiệu</span>
            <span className="ml-auto flex items-center gap-2 text-[10px] text-[var(--color-muted)]">
              <OutcomeDot o="tp" /> chạm TP <OutcomeDot o="sl" /> chạm SL <OutcomeDot o="open" /> chưa chạm
            </span>
          </div>

          {/* Timeline trực quan */}
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
            <div className="mb-2 text-[11px] text-[var(--color-muted)]">Dòng thời gian tín hiệu {sym} (mục tiêu {target === "std3_outcome" ? "±3%" : "+6%/−4%"}) — mỗi chấm 1 tín hiệu:</div>
            <div className="flex flex-wrap items-end gap-1">
              {symRows.map((r) => {
                const o = r[target] as string | null;
                const ret = num(r.ret_5d);
                return (
                  <div key={r.pred_id} className="flex flex-col items-center gap-0.5" title={`${r.signal_date} · ${outcomeMeta(o).label} · lãi5=${ret != null ? ret.toFixed(1) + "%" : "—"}`}>
                    <OutcomeDot o={o} />
                    <span className="text-[8px] text-[var(--color-muted)]">{r.signal_date.slice(5)}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Bảng chi tiết */}
          <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left text-[var(--color-muted)]">
                  <th className="px-2 py-1.5 font-medium">Ngày</th>
                  <th className="px-2 py-1.5 font-medium">QĐ</th>
                  <th className="px-2 py-1.5 font-medium">Chất lượng</th>
                  <th className="px-2 py-1.5 font-medium">Giá t0</th>
                  <th className="px-2 py-1.5 font-medium">Kết quả ±3%</th>
                  <th className="px-2 py-1.5 font-medium">Kết quả +6/−4</th>
                  <th className="px-2 py-1.5 font-medium">TP/SL model</th>
                  <th className="px-2 py-1.5 text-right font-medium">Lãi 5 phiên</th>
                  <th className="px-2 py-1.5 text-right font-medium">Đỉnh/Đáy (MFE/MAE)</th>
                </tr>
              </thead>
              <tbody>
                {symRows.slice().reverse().map((r) => {
                  const o3 = outcomeMeta(r.std3_outcome);
                  const o6 = outcomeMeta(r.std_outcome);
                  const oOwn = outcomeMeta(r.own_outcome);
                  const ret5 = num(r.ret_5d);
                  return (
                    <tr key={r.pred_id} className="border-b border-[var(--color-border)] last:border-0">
                      <td className="px-2 py-1.5 tabular">{r.signal_date}</td>
                      <td className="px-2 py-1.5"><DecisionBadge decision={r.decision} /></td>
                      <td className="px-2 py-1.5"><ConfMini conf={r.confidence} /></td>
                      <td className="px-2 py-1.5 tabular">{fmtNum(r.t0_close)}</td>
                      <td className="px-2 py-1.5"><span className="inline-flex items-center gap-1"><OutcomeDot o={r.std3_outcome} /><span style={{ color: o3.color }}>{o3.label}</span></span></td>
                      <td className="px-2 py-1.5"><span className="inline-flex items-center gap-1"><OutcomeDot o={r.std_outcome} /><span style={{ color: o6.color }}>{o6.label}{r.std_outcome === "tp" || r.std_outcome === "sl" ? ` · ${num(r.std_days) ?? "?"}n` : ""}</span></span></td>
                      <td className="px-2 py-1.5" style={{ color: oOwn.color }}>{r.own_outcome == null ? "—" : oOwn.label}</td>
                      <td className="px-2 py-1.5 text-right tabular"><span className={signClass(ret5)}>{ret5 != null ? fmtPct(ret5) : "—"}</span></td>
                      <td className="px-2 py-1.5 text-right tabular"><span style={{ color: BUY }}>{num(r.mfe_pct) != null ? "+" + num(r.mfe_pct)!.toFixed(1) : "—"}</span> / <span style={{ color: SELL }}>{num(r.mae_pct) != null ? num(r.mae_pct)!.toFixed(1) : "—"}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] italic text-[var(--color-muted)]">
            “Kết quả” = giá chạm mục tiêu chốt hay mức cắt trước, tính theo nến thật trong ~10 phiên sau tín hiệu.
            “TP/SL model” = TP/SL riêng model đặt lúc đó (chỉ có từ T9/2026). MFE/MAE = mức lãi/lỗ tối đa trong cửa sổ.
          </p>
        </div>
      )}
    </div>
  );
}
