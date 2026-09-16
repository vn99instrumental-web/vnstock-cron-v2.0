"use client";

import { useMemo, useState } from "react";
import { DecisionBadge } from "@/components/ui";
import { fmtNum, fmtPct, signClass } from "@/lib/format";
import { varName, GROUP_LABEL, GROUP_ORDER, CONFIDENCE_LABEL } from "@/lib/interpret";
import { CorrHeatmap, type FactorPair } from "@/components/corr-heatmap";
import { SignalTimeline } from "@/components/signal-timeline";

export type { FactorPair };

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
  grp: string | null;
}

export interface FactorCorrSplit {
  dim: string;      // "confidence" | "regime"
  bucket: string;
  factor: string;
  n: number;
  corr_ret5: number | string | null;
  corr_win: number | string | null;
  grp: string | null;
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

export function AnalysisBoard({
  results, corr, pairs = [], split = [],
}: {
  results: SignalResult[];
  corr: FactorCorr[];
  pairs?: FactorPair[];
  split?: FactorCorrSplit[];
}) {
  const [tab, setTab] = useState<"overall" | "symbol">("overall");
  const [target, setTarget] = useState<TargetKey>("std3_outcome");
  const [corrMetric, setCorrMetric] = useState<"corr_ret5" | "corr_win">("corr_ret5");
  const [grpFilter, setGrpFilter] = useState<string>("all");
  const [splitDim, setSplitDim] = useState<"none" | "confidence" | "regime">("none");
  const [bucket, setBucket] = useState<string>("");
  const [showAllCorr, setShowAllCorr] = useState(false);

  // GỘP THEO NGÀY: outcome forward tính 1 lần/ngày nên mọi snap cùng ngày giống hệt.
  // Giữ 1 dòng/(mã, ngày) — snap MUỘN nhất trong ngày — để không lặp & thấy khác biệt qua ngày.
  const dailyResults = useMemo(() => {
    const byKey = new Map<string, SignalResult>();
    for (const r of results) {
      const k = `${r.symbol}|${r.signal_date}`;
      const prev = byKey.get(k);
      if (!prev || String(r.snap_time) > String(prev.snap_time)) byKey.set(k, r);
    }
    return [...byKey.values()];
  }, [results]);

  const symbols = useMemo(
    () => [...new Set(dailyResults.map((r) => r.symbol))].sort(),
    [dailyResults],
  );
  const [sym, setSym] = useState<string>(symbols[0] ?? "");

  // Khung dữ liệu (độ tươi, phạm vi).
  const meta = useMemo(() => {
    const dates = dailyResults.map((r) => r.signal_date).sort();
    const hasOwn = dailyResults.some((r) => r.own_outcome != null);
    return { n: dailyResults.length, nSym: symbols.length, d0: dates[0], d1: dates[dates.length - 1], hasOwn };
  }, [dailyResults, symbols]);

  // Đếm kết quả cho target đang chọn (tổng + theo quyết định) — theo NGÀY.
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
      all: tally(dailyResults),
      buy: tally(dailyResults.filter((r) => r.decision === "BUY")),
      sbuy: tally(dailyResults.filter((r) => r.decision === "STRONG BUY")),
    };
  }, [dailyResults, target]);

  const grpsPresent = useMemo(
    () => GROUP_ORDER.filter((g) => corr.some((c) => c.grp === g)),
    [corr],
  );

  // Buckets cho split đang chọn (confidence: HIGH/MEDIUM/LOW; regime: theo n giảm dần).
  const buckets = useMemo(() => {
    if (splitDim === "none") return [] as { bucket: string; n: number }[];
    const m = new Map<string, number>();
    for (const s of split) if (s.dim === splitDim) m.set(s.bucket, Math.max(m.get(s.bucket) ?? 0, s.n));
    const arr = [...m.entries()];
    if (splitDim === "confidence") {
      const ord = ["HIGH", "MEDIUM", "LOW"];
      arr.sort((a, b) => ord.indexOf(a[0]) - ord.indexOf(b[0]));
    } else arr.sort((a, b) => b[1] - a[1]);
    return arr.map(([b, n]) => ({ bucket: b, n }));
  }, [split, splitDim]);
  const activeBucket = buckets.some((b) => b.bucket === bucket) ? bucket : (buckets[0]?.bucket ?? "");

  // Nguồn corr đang hiển thị: toàn cục hoặc theo bucket.
  const activeCorr = useMemo<(FactorCorr | FactorCorrSplit)[]>(
    () => (splitDim === "none" ? corr : split.filter((s) => s.dim === splitDim && s.bucket === activeBucket)),
    [splitDim, corr, split, activeBucket],
  );
  const corrSorted = useMemo(
    () =>
      activeCorr
        .map((c) => ({ factor: c.factor, grp: c.grp, n: c.n, v: num(c[corrMetric]) }))
        .filter((c) => c.v != null && (grpFilter === "all" || c.grp === grpFilter))
        .sort((a, b) => Math.abs(b.v!) - Math.abs(a.v!)),
    [activeCorr, corrMetric, grpFilter],
  );
  const corrMax = useMemo(
    () => Math.max(0.2, ...activeCorr.map((c) => Math.abs(num(c[corrMetric]) ?? 0))),
    [activeCorr, corrMetric],
  );

  // Tập biến cho heatmap: theo nhóm đang chọn; nếu "tất cả" → 10 biến mạnh nhất (đọc dễ).
  const heatFactors = useMemo(() => {
    if (grpFilter !== "all") return corr.filter((c) => c.grp === grpFilter).map((c) => c.factor).slice(0, 12);
    return [...corr]
      .map((c) => ({ f: c.factor, v: Math.abs(num(c.corr_ret5) ?? 0) }))
      .sort((a, b) => b.v - a.v)
      .slice(0, 10)
      .map((x) => x.f);
  }, [corr, grpFilter]);

  // Cặp biến gần trùng — quét TOÀN BỘ biến (đa cộng tuyến), để cảnh báo luôn nổi.
  const nearDup = useMemo(
    () =>
      pairs
        .map((p) => ({ ...p, v: num(p.corr) }))
        .filter((p) => p.v != null && Math.abs(p.v) >= 0.9)
        .sort((a, b) => Math.abs(b.v!) - Math.abs(a.v!))
        .slice(0, 6),
    [pairs],
  );

  const symRows = useMemo(
    () => dailyResults.filter((r) => r.symbol === sym).sort((a, b) => a.signal_date.localeCompare(b.signal_date)),
    [dailyResults, sym],
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
      {/* Phạm vi dữ liệu — KPI tiles gọn, dễ quét */}
      <div className="flex flex-wrap items-stretch gap-2">
        {[
          { v: meta.n, lb: "tín hiệu-ngày đã chín" },
          { v: meta.nSym, lb: "mã" },
          { v: `${meta.d0?.slice(5) ?? "?"} → ${meta.d1?.slice(5) ?? "?"}`, lb: "khoảng thời gian" },
        ].map((t) => (
          <div key={t.lb} className="flex min-w-[92px] flex-1 flex-col rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
            <span className="text-base font-semibold tabular">{t.v}</span>
            <span className="text-[10px] text-[var(--color-muted)]">{t.lb}</span>
          </div>
        ))}
      </div>

      {/* Cách đọc & giới hạn — thu gọn, không lấn nội dung */}
      <details className="rounded-md border border-[var(--color-border)] bg-black/[0.015] px-3 py-1.5 text-[11px] text-[var(--color-muted)] dark:bg-white/[0.03]">
        <summary className="cursor-pointer select-none font-medium text-[var(--color-ink)]">ℹ️ Cách đọc &amp; giới hạn dữ liệu</summary>
        <div className="mt-1.5 flex flex-col gap-1">
          <p>• Kết quả “chạm TP/SL” xác định bằng <b className="text-[var(--color-ink)]">đường giá nến thật</b> — chạm cái nào trước, theo ngày.</p>
          <p>• Tương quan biến là <b className="text-[var(--color-ink)]">khám phá</b> (mẫu 1 tháng), <i>không phải IC chính thức</i> — IC chuẩn ở tab Chất lượng (IC).</p>
          {!meta.hasOwn ? (
            <p className="text-[var(--color-sell)]">• TP/SL <b>riêng</b> của model chỉ lưu từ T9/2026 → chưa mã nào đủ chín; tạm dùng mục tiêu chuẩn ±%. Cột “own” sẽ tự đầy từ cuối T9.</p>
          ) : null}
        </div>
      </details>

      {/* Tab segmented */}
      <div className="inline-flex w-fit rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5">
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
            <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
              <h3 className="text-sm font-semibold">Biến nào liên quan kết quả?</h3>
              <span className="text-[10px] text-[var(--color-muted)]">{corr.length} biến · đã loại biến rò rỉ/ID</span>
              <div className="ml-auto inline-flex rounded-md border border-[var(--color-border)] p-0.5 text-[11px]">
                {([["corr_ret5", "vs lãi 5 phiên"], ["corr_win", "vs chạm TP"]] as const).map(([k, lb]) => (
                  <button key={k} onClick={() => setCorrMetric(k)} className={`rounded px-2 py-0.5 ${corrMetric === k ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-muted)]"}`}>{lb}</button>
                ))}
              </div>
            </div>
            {/* Toolbar: nhóm biến */}
            <div className="mb-1.5 flex flex-wrap items-center gap-1 text-[10px]">
              <span className="mr-0.5 text-[var(--color-muted)]">Nhóm:</span>
              <button onClick={() => setGrpFilter("all")} className={`rounded-full border px-2 py-0.5 ${grpFilter === "all" ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-muted)]"}`}>Tất cả</button>
              {grpsPresent.map((g) => (
                <button key={g} onClick={() => setGrpFilter(g)} className={`rounded-full border px-2 py-0.5 ${grpFilter === g ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-muted)]"}`}>{GROUP_LABEL[g] ?? g}</button>
              ))}
            </div>
            {/* Toolbar: tách theo bối cảnh */}
            <div className="mb-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px]">
              <span className="text-[var(--color-muted)]">Tách theo:</span>
              <div className="inline-flex rounded-md border border-[var(--color-border)] p-0.5">
                {([["none", "Không tách"], ["confidence", "Chất lượng"], ["regime", "Trạng thái TT"]] as const).map(([k, lb]) => (
                  <button key={k} onClick={() => setSplitDim(k)} className={`rounded px-2 py-0.5 ${splitDim === k ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-muted)]"}`}>{lb}</button>
                ))}
              </div>
              {splitDim !== "none" ? (
                <span className="flex flex-wrap items-center gap-1">
                  {buckets.map((b) => (
                    <button key={b.bucket} onClick={() => setBucket(b.bucket)} className={`rounded-full border px-2 py-0.5 ${activeBucket === b.bucket ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-muted)]"}`} title={b.n < 40 ? "Mẫu nhỏ — đọc dè dặt" : ""}>
                      {b.bucket} <span className="opacity-70">{b.n}{b.n < 40 ? "⚠" : ""}</span>
                    </button>
                  ))}
                </span>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              {(showAllCorr ? corrSorted : corrSorted.slice(0, 12)).map((c) => {
                const v = c.v!;
                const w = Math.min(50, (Math.abs(v) / corrMax) * 50);
                const color = v >= 0 ? BUY : SELL;
                return (
                  <div key={c.factor} className="flex items-center gap-2 text-[11px]">
                    <span className="w-28 shrink-0 truncate sm:w-44" title={`${c.factor} · n=${c.n}`}>{varName(c.factor)}</span>
                    <div className="relative h-3.5 flex-1 rounded bg-black/[0.06] dark:bg-white/10">
                      <div className="absolute left-1/2 top-0 h-3.5 w-px bg-[var(--color-border)]" />
                      <div className="absolute top-0 h-3.5 rounded" style={{ backgroundColor: color, left: v >= 0 ? "50%" : `${50 - w}%`, width: `${w}%` }} />
                    </div>
                    <span className="tabular w-11 shrink-0 text-right font-medium" style={{ color }}>{v >= 0 ? "+" : ""}{v.toFixed(2)}</span>
                  </div>
                );
              })}
              {corrSorted.length === 0 ? <div className="py-3 text-center text-[11px] text-[var(--color-muted)]">Không có biến trong nhóm này.</div> : null}
            </div>
            {corrSorted.length > 12 ? (
              <button onClick={() => setShowAllCorr((v) => !v)} className="mt-2 text-[11px] font-medium text-[var(--color-accent)] hover:underline">
                {showAllCorr ? "▴ Thu gọn" : `▾ Xem tất cả ${corrSorted.length} biến`}
              </button>
            ) : null}
            <p className="mt-2 border-t border-[var(--color-border)] pt-2 text-[10px] italic text-[var(--color-muted)]">
              <span style={{ color: BUY }}>▮</span> càng cao càng tốt · <span style={{ color: SELL }}>▮</span> càng cao càng xấu · độ dài = độ mạnh.
              {splitDim !== "none" ? <> Đang tách theo <b>{splitDim === "confidence" ? "chất lượng" : "trạng thái TT"}</b> — nhiều biến đổi dấu giữa các bucket.</> : null}
              {" "}Gợi ý soi trọng số, <b>không</b> phải nhân quả (mẫu 1 tháng).
            </p>
          </div>

          {/* Ma trận tương quan biến×biến (bắt biến trùng / đa cộng tuyến) */}
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
            <h3 className="mb-2 text-sm font-semibold">
              Biến nào trùng nhau?
              <span className="ml-1 text-[11px] font-normal text-[var(--color-muted)]">(phát hiện đa cộng tuyến để bớt biến thừa)</span>
            </h3>
            {nearDup.length ? (
              <div className="mb-3 rounded-md border-l-2 border-amber-500 bg-amber-500/10 px-3 py-2 text-[11px]">
                <div className="mb-1 font-medium text-amber-700 dark:text-amber-400">⚠ {nearDup.length} cặp biến gần như trùng nhau — nên gộp/bỏ bớt 1 khi chỉnh trọng số:</div>
                <div className="flex flex-col gap-0.5">
                  {nearDup.map((p) => (
                    <div key={`${p.fa}|${p.fb}`} className="flex items-center gap-2">
                      <span className="tabular w-10 shrink-0 font-semibold" style={{ color: p.v! >= 0 ? BUY : SELL }}>{p.v! >= 0 ? "+" : ""}{p.v!.toFixed(2)}</span>
                      <span>{varName(p.fa)} <span className="text-[var(--color-muted)]">≈</span> {varName(p.fb)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <details>
              <summary className="cursor-pointer select-none text-[11px] font-medium text-[var(--color-muted)] hover:text-[var(--color-ink)]">
                🔬 Xem ma trận đầy đủ — {grpFilter === "all" ? "10 biến mạnh nhất" : GROUP_LABEL[grpFilter] ?? grpFilter}
              </summary>
              <div className="mt-2">
                <CorrHeatmap pairs={pairs} factors={heatFactors} />
              </div>
            </details>
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
            <span className="text-[var(--color-muted)]">{symRows.length} ngày có tín hiệu</span>
            <span className="ml-auto flex items-center gap-2 text-[10px] text-[var(--color-muted)]">
              <OutcomeDot o="tp" /> chạm TP <OutcomeDot o="sl" /> chạm SL <OutcomeDot o="open" /> chưa chạm
            </span>
          </div>

          {/* Timeline trực quan: cột = lãi 5 phiên, màu = kết quả */}
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
            <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
              <h3 className="text-sm font-semibold">Diễn biến tín hiệu {sym} theo thời gian</h3>
              <span className="text-[10px] text-[var(--color-muted)]">cột = lãi 5 phiên · màu = kết quả</span>
              <div className="ml-auto inline-flex rounded-md border border-[var(--color-border)] p-0.5 text-[10px]">
                {([["std3_outcome", "±3%"], ["std_outcome", "+6/−4"]] as const).map(([k, lb]) => (
                  <button key={k} onClick={() => setTarget(k)} className={`rounded px-2 py-0.5 ${target === k ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-muted)]"}`}>{lb}</button>
                ))}
              </div>
            </div>
            <SignalTimeline rows={symRows} target={target} />
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
