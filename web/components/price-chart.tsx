"use client";

import { useEffect, useRef, useState } from "react";
import type { Candle, Levels } from "@/lib/chart";
import { computeBB, computeEMA } from "@/lib/chart";

// Chart nến custom SVG (interactive). Hover → crosshair + tooltip. Ctrl+lăn = zoom
// quanh con trỏ, kéo = pan (kiểu TradingView).
// Overlay: Entry + đường ±3/±6% (màu xanh/đỏ theo hướng), EMA50/EMA200, Bollinger(20,2).
// KHÔNG còn TP/SL (thay bằng ±3/6%). ◆ hồng = điểm tín hiệu BUY.

const W = 820;
const H = 340;
const M = { top: 12, right: 66, bottom: 30, left: 46 };
const MIN_VIS = 5;

const UP = "#16a34a";
const DOWN = "#dc2626";
const ACCENT = "#2563eb";
const EMA50C = "#ea580c";
const EMA200C = "#7c3aed";
const BUYC = "#db2777";
const BBC = "#64748b";
// màu đường % (đậm dần theo mức)
const PCT_COLOR: Record<number, string> = { 6: "#15803d", 3: "#4ade80", [-3]: "#f87171", [-6]: "#dc2626" };

function fmt(n: number): string {
  return n.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function clamp(v: number, lo: number, hi: number) { return Math.max(lo, Math.min(hi, v)); }

export interface BuyMarker { date: string; price: number; strong: boolean }

export function PriceChart({
  candles,
  levels,
  buyMarkers = [],
}: {
  candles: Candle[];
  levels: Levels;
  buyMarkers?: BuyMarker[];
}) {
  const n = candles.length;
  const wrapRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ start: 0, count: n });
  const [hover, setHover] = useState<number | null>(null);
  const drag = useRef<{ active: boolean } | null>(null);

  useEffect(() => { setView({ start: 0, count: n }); }, [n]);

  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const vx = ((e.clientX - rect.left) / rect.width) * W;
      const frac = clamp((vx - M.left) / plotW, 0, 1);
      setView((prev) => {
        const anchor = prev.start + frac * prev.count;
        const factor = e.deltaY < 0 ? 0.82 : 1.22;
        const count = Math.round(clamp(prev.count * factor, MIN_VIS, n));
        let s = Math.round(anchor - frac * count);
        s = clamp(s, 0, Math.max(0, n - count));
        return { start: s, count };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [n, plotW]);

  if (!n) return <p className="p-6 text-xs text-[var(--color-muted)]">Chưa đủ dữ liệu giá để vẽ.</p>;

  const start = clamp(view.start, 0, Math.max(0, n - Math.min(view.count, n)));
  const count = clamp(view.count, MIN_VIS, n);
  const end = Math.min(n, start + count);
  const vis = candles.slice(start, end);
  const m = vis.length;

  const ys = vis.flatMap((c) => [c.high, c.low]);
  let yMin = Math.min(...ys);
  let yMax = Math.max(...ys);
  const pad = (yMax - yMin) * 0.06 || yMax * 0.02 || 1;
  yMin -= pad; yMax += pad;
  const y = (v: number) => M.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  const inY = (v: number | null | undefined): v is number => v != null && v >= yMin && v <= yMax;

  const slot = plotW / m;
  const cw = Math.max(1.5, Math.min(14, slot * 0.62));
  const cx = (localI: number) => M.left + slot * (localI + 0.5);

  const lastBuy = buyMarkers.length ? buyMarkers[buyMarkers.length - 1].price : null;
  const base = levels.entry ?? lastBuy;
  const pctPairs = base != null ? [6, 3, -3, -6].map((p) => ({ p, v: base * (1 + p / 100) })) : [];

  // Sau ngày tín hiệu: đã đạt +3/+6% (high) hay thủng -3/-6% (low)?
  const reach = { up3: false, up6: false, dn3: false, dn6: false };
  if (base != null) {
    for (const c of candles) {
      if (c.date < levels.signalDate) continue;
      if (c.high >= base * 1.06) reach.up6 = true;
      if (c.high >= base * 1.03) reach.up3 = true;
      if (c.low <= base * 0.94) reach.dn6 = true;
      if (c.low <= base * 0.97) reach.dn3 = true;
    }
  }

  const ema50 = computeEMA(candles, 50);
  const ema200 = computeEMA(candles, 200);
  const bb = computeBB(candles, 20, 2);
  const line = (vals: (number | null)[], col: string, sw = 1.2, dash?: string) => {
    const pts: string[] = [];
    for (let g = start; g < end; g++) { const v = vals[g]; if (v != null) pts.push(`${cx(g - start)},${y(v)}`); }
    return pts.length ? <polyline points={pts.join(" ")} fill="none" stroke={col} strokeWidth={sw} strokeDasharray={dash} opacity={0.9} /> : null;
  };
  const emaHas = { e50: ema50.slice(start, end).some((v) => v != null), e200: ema200.slice(start, end).some((v) => v != null) };

  // Bollinger fill band (upper→lower) trong vùng xem.
  const bbUpper: (number | null)[] = bb.map((b) => b.upper);
  const bbLower: (number | null)[] = bb.map((b) => b.lower);
  const bbMid: (number | null)[] = bb.map((b) => b.mid);
  let bbBand: string | null = null;
  {
    const up: string[] = [], lo: string[] = [];
    for (let g = start; g < end; g++) {
      if (bbUpper[g] != null && bbLower[g] != null) {
        up.push(`${cx(g - start)},${y(bbUpper[g] as number)}`);
        lo.push(`${cx(g - start)},${y(bbLower[g] as number)}`);
      }
    }
    if (up.length > 1) bbBand = up.join(" ") + " " + lo.reverse().join(" ");
  }

  const yTicks = Array.from({ length: 5 }, (_, k) => yMin + ((yMax - yMin) * k) / 4);
  const sigGlobal = candles.findIndex((c) => c.date >= levels.signalDate);
  const sigLocal = sigGlobal >= start && sigGlobal < end ? sigGlobal - start : -1;
  const step = Math.max(1, Math.ceil(m / 10));
  const xLabels = new Set<number>();
  for (let i = 0; i < m; i += step) xLabels.add(i);
  xLabels.add(m - 1);
  if (sigLocal >= 0) xLabels.add(sigLocal);

  function localFromEvent(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    return clamp(Math.round((vx - M.left) / slot - 0.5), 0, m - 1);
  }
  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    if (drag.current?.active) {
      const rect = e.currentTarget.getBoundingClientRect();
      const dCandles = Math.round((e.movementX / rect.width) * W / slot);
      if (dCandles !== 0) setView((prev) => {
        const cnt = clamp(prev.count, MIN_VIS, n);
        return { start: clamp(prev.start - dCandles, 0, Math.max(0, n - cnt)), count: cnt };
      });
      return;
    }
    setHover(start + localFromEvent(e));
  }

  const hc = hover != null && hover >= start && hover < end ? candles[hover] : null;
  const hoverLocal = hc ? hover! - start : -1;

  return (
    <div ref={wrapRef} className="relative w-full overflow-hidden">
      <svg
        viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Chart giá"
        style={{ cursor: "crosshair" }}
        onMouseMove={onMove}
        onMouseLeave={() => { setHover(null); drag.current = null; }}
        onMouseDown={() => { drag.current = { active: true }; }}
        onMouseUp={() => { drag.current = null; }}
      >
        {yTicks.map((t, k) => (
          <g key={k}>
            <line x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--color-border)" strokeWidth={0.5} />
            <text x={M.left - 5} y={y(t) + 3} fontSize={9} textAnchor="end" fill="var(--color-muted)" className="tabular">{fmt(t)}</text>
          </g>
        ))}

        {/* Bollinger band (nền mờ) */}
        {bbBand ? <polygon points={bbBand} fill={BBC} opacity={0.08} /> : null}
        {line(bbUpper, BBC, 0.8, "3 2")}
        {line(bbLower, BBC, 0.8, "3 2")}
        {line(bbMid, BBC, 0.8, "1 2")}

        {/* đường ±3/±6% quanh entry — màu xanh/đỏ rõ */}
        {pctPairs.filter(({ v }) => inY(v)).map(({ p, v }) => (
          <g key={p}>
            <line x1={M.left} x2={M.left + plotW} y1={y(v)} y2={y(v)} stroke={PCT_COLOR[p]} strokeWidth={1} strokeDasharray="5 3" opacity={0.9} />
            <text x={M.left + plotW + 4} y={y(v) + 3} fontSize={9} fill={PCT_COLOR[p]} className="tabular">{p > 0 ? "+" : ""}{p}% {fmt(v)}</text>
          </g>
        ))}

        {/* nến */}
        {vis.map((c, i) => {
          const up = c.close >= c.open;
          const col = up ? UP : DOWN;
          const bodyTop = y(Math.max(c.open, c.close));
          const bodyBot = y(Math.min(c.open, c.close));
          return (
            <g key={c.date}>
              <line x1={cx(i)} x2={cx(i)} y1={y(c.high)} y2={y(c.low)} stroke={col} strokeWidth={1} />
              <rect x={cx(i) - cw / 2} y={bodyTop} width={cw} height={Math.max(1, bodyBot - bodyTop)} fill={col} />
            </g>
          );
        })}

        {line(ema50, EMA50C)}
        {line(ema200, EMA200C)}

        {sigLocal >= 0 ? (
          <line x1={cx(sigLocal)} x2={cx(sigLocal)} y1={M.top} y2={M.top + plotH} stroke={ACCENT} strokeWidth={0.5} strokeDasharray="2 2" opacity={0.5} />
        ) : null}

        {/* Entry (giữ lại làm mốc gốc) */}
        {inY(levels.entry) ? (
          <g>
            <line x1={M.left} x2={M.left + plotW} y1={y(levels.entry)} y2={y(levels.entry)} stroke={ACCENT} strokeWidth={1} opacity={0.9} />
            <text x={M.left + plotW + 4} y={y(levels.entry) + 3} fontSize={9} fill={ACCENT} className="tabular">Entry {fmt(levels.entry)}</text>
          </g>
        ) : null}

        {buyMarkers.map((mk, k) => {
          const g = candles.findIndex((c) => c.date === mk.date);
          const li = g - start;
          if (li < 0 || li >= m || !inY(mk.price)) return null;
          const px = cx(li), py = y(mk.price), r = mk.strong ? 5 : 4;
          return (
            <path key={k} d={`M ${px} ${py - r} L ${px + r} ${py} L ${px} ${py + r} L ${px - r} ${py} Z`}
              fill={BUYC} stroke="#fff" strokeWidth={1}>
              <title>{mk.date} · {mk.strong ? "STRONG BUY" : "BUY"} @ {fmt(mk.price)}</title>
            </path>
          );
        })}

        {hoverLocal >= 0 ? (
          <line x1={cx(hoverLocal)} x2={cx(hoverLocal)} y1={M.top} y2={M.top + plotH} stroke="var(--color-ink)" strokeWidth={0.5} opacity={0.35} />
        ) : null}

        {[...xLabels].sort((a, b) => a - b).map((i) => (
          <text key={i} x={cx(i)} y={H - 6} fontSize={8} textAnchor="middle" fill="var(--color-muted)">{vis[i]?.date.slice(5)}</text>
        ))}
      </svg>

      {hc ? (
        <div className="pointer-events-none absolute right-2 top-2 rounded border border-[var(--color-border)] bg-[var(--color-surface)]/95 px-2 py-1 text-[10px] tabular shadow-sm">
          <div className="font-semibold">{hc.date}</div>
          <div className="mt-0.5 grid grid-cols-2 gap-x-2">
            <span className="text-[var(--color-muted)]">O</span><span className="text-right">{fmt(hc.open)}</span>
            <span className="text-[var(--color-muted)]">H</span><span className="text-right">{fmt(hc.high)}</span>
            <span className="text-[var(--color-muted)]">L</span><span className="text-right">{fmt(hc.low)}</span>
            <span className="text-[var(--color-muted)]">C</span>
            <span className="text-right" style={{ color: hc.close >= hc.open ? UP : DOWN }}>{fmt(hc.close)}</span>
          </div>
        </div>
      ) : null}

      <div className="pointer-events-none absolute left-2 top-2">
        {count < n ? (
          <button onClick={() => setView({ start: 0, count: n })}
            className="pointer-events-auto rounded border border-[var(--color-border)] bg-[var(--color-surface)]/90 px-1.5 py-0.5 text-[10px] text-[var(--color-muted)] hover:text-[var(--color-ink)]">
            ⟳ toàn bộ ({n})
          </button>
        ) : null}
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[10px] text-[var(--color-muted)]">
        {emaHas.e50 ? <span><span style={{ color: EMA50C }}>—</span> EMA50</span> : null}
        {emaHas.e200 ? <span><span style={{ color: EMA200C }}>—</span> EMA200</span>
          : <span className="italic">EMA200 cần ≥200 phiên (hiện {n})</span>}
        <span><span style={{ color: BBC }}>▭</span> Bollinger(20,2)</span>
        <span><span style={{ color: ACCENT }}>—</span> Entry</span>
        <span><span style={{ color: PCT_COLOR[3] }}>┈</span> +3/+6% · <span style={{ color: PCT_COLOR[-3] }}>┈</span> −3/−6%</span>
        <span><span style={{ color: BUYC }}>◆</span> BUY</span>
        {reach.up3 ? <span className="text-[var(--color-buy)]">✓ đạt +3%{reach.up6 ? "/+6%" : ""}</span> : null}
        {reach.dn3 ? <span className="text-[var(--color-sell)]">▼ thủng −3%{reach.dn6 ? "/−6%" : ""}</span> : null}
        <span className="ml-auto italic">Ctrl+lăn = zoom · kéo = pan · {count}/{n} phiên</span>
      </div>
    </div>
  );
}

// Strip intraday: giá theo từng snap trong ngày ra tín hiệu.
export function IntradayStrip({ candle }: { candle: Candle | undefined }) {
  if (!candle || candle.snaps.length < 2) {
    return <p className="text-[10px] text-[var(--color-muted)]">Ngày ra tín hiệu chỉ có 1 điểm giá — không đủ vẽ intraday.</p>;
  }
  const w = 820, h = 80, m = { l: 46, r: 66, t: 6, b: 16 };
  const pw = w - m.l - m.r, ph = h - m.t - m.b;
  const prices = candle.snaps.map((s) => s.price);
  let lo = Math.min(...prices), hi = Math.max(...prices);
  const pad = (hi - lo) * 0.15 || hi * 0.01 || 0.5;
  lo -= pad; hi += pad;
  const nn = candle.snaps.length;
  const x = (i: number) => m.l + (nn === 1 ? pw / 2 : (pw * i) / (nn - 1));
  const y = (v: number) => m.t + ph - ((v - lo) / (hi - lo)) * ph;
  const up = prices[nn - 1] >= prices[0];
  const col = up ? UP : DOWN;
  const pts = candle.snaps.map((s, i) => `${x(i)},${y(s.price)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label="Giá intraday">
      <polyline points={pts} fill="none" stroke={col} strokeWidth={1.5} />
      {candle.snaps.map((s, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(s.price)} r={2} fill={col} />
          <text x={x(i)} y={h - 4} fontSize={8} textAnchor="middle" fill="var(--color-muted)">{s.t}</text>
        </g>
      ))}
      <text x={m.l - 5} y={y(hi) + 7} fontSize={8} textAnchor="end" fill="var(--color-muted)" className="tabular">{fmt(hi)}</text>
      <text x={m.l - 5} y={y(lo) + 2} fontSize={8} textAnchor="end" fill="var(--color-muted)" className="tabular">{fmt(lo)}</text>
    </svg>
  );
}
