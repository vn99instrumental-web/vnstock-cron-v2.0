"use client";

import { useState } from "react";
import type { Candle, Levels } from "@/lib/chart";
import { computeMA, tpHit } from "@/lib/chart";

// Chart nến custom SVG (interactive). Hover → crosshair + tooltip OHLC/ngày.
// Overlay entry/stop/tp1/tp2 + MA5/MA10. ◆ hồng = điểm tín hiệu BUY. ★ = chạm TP.

const W = 800;
const H = 320;
const M = { top: 12, right: 60, bottom: 30, left: 44 };

const UP = "#16a34a";
const DOWN = "#dc2626";
const ACCENT = "#2563eb";
const MA5C = "#0891b2";
const MA10C = "#ca8a04";
const BUYC = "#db2777"; // hồng cánh sen — tách khỏi nến xanh & entry xanh dương

function fmt(n: number): string {
  return n.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

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
  const [hover, setHover] = useState<number | null>(null);

  if (!candles.length) {
    return <p className="p-6 text-xs text-[var(--color-muted)]">Chưa đủ dữ liệu giá để vẽ.</p>;
  }

  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;

  const ys = candles.flatMap((c) => [c.high, c.low]);
  for (const v of [levels.entry, levels.stop, levels.tp1, levels.tp2]) if (v != null) ys.push(v);
  let yMin = Math.min(...ys);
  let yMax = Math.max(...ys);
  const pad = (yMax - yMin) * 0.08 || yMax * 0.02 || 1;
  yMin -= pad;
  yMax += pad;

  const y = (v: number) => M.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  const n = candles.length;
  const slot = plotW / n;
  const cw = Math.max(2, Math.min(12, slot * 0.6));
  const cx = (i: number) => M.left + slot * (i + 0.5);
  const idxOf = new Map(candles.map((c, i) => [c.date, i]));

  const { hit1, hit2, hitStop } = tpHit(candles, levels);
  const ma5 = computeMA(candles, 5);
  const ma10 = computeMA(candles, 10);
  const maPath = (ma: (number | null)[], col: string) => {
    const pts = ma.map((v, i) => (v == null ? null : `${cx(i)},${y(v)}`)).filter(Boolean).join(" ");
    return pts ? <polyline points={pts} fill="none" stroke={col} strokeWidth={1} opacity={0.85} /> : null;
  };

  const yTicks = Array.from({ length: 5 }, (_, k) => yMin + ((yMax - yMin) * k) / 4);

  // Nhãn ngày dưới trục: ~7 mốc đều nhau + ngày tín hiệu.
  const sigIdx = candles.findIndex((c) => c.date >= levels.signalDate);
  const step = Math.max(1, Math.ceil(n / 7));
  const xLabels = new Set<number>();
  for (let i = 0; i < n; i += step) xLabels.add(i);
  xLabels.add(n - 1);
  if (sigIdx >= 0) xLabels.add(sigIdx);

  function level(v: number | null, color: string, dash: string, label: string) {
    if (v == null) return null;
    const yy = y(v);
    return (
      <g>
        <line x1={M.left} x2={M.left + plotW} y1={yy} y2={yy} stroke={color} strokeWidth={1} strokeDasharray={dash} opacity={0.9} />
        <text x={M.left + plotW + 4} y={yy + 3} fontSize={9} fill={color} className="tabular">{label} {fmt(v)}</text>
      </g>
    );
  }

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    let i = Math.round((vx - M.left) / slot - 0.5);
    i = Math.max(0, Math.min(n - 1, i));
    setHover(i);
  }

  const hc = hover != null ? candles[hover] : null;

  return (
    <div className="relative w-full overflow-hidden">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label="Chart giá"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {yTicks.map((t, k) => (
          <g key={k}>
            <line x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--color-border)" strokeWidth={0.5} />
            <text x={M.left - 5} y={y(t) + 3} fontSize={9} textAnchor="end" fill="var(--color-muted)" className="tabular">{fmt(t)}</text>
          </g>
        ))}

        {/* nến */}
        {candles.map((c, i) => {
          const up = c.close >= c.open;
          const col = up ? UP : DOWN;
          const bodyTop = y(Math.max(c.open, c.close));
          const bodyBot = y(Math.min(c.open, c.close));
          const isHit = levels.tp1 != null && c.date >= levels.signalDate && c.high >= levels.tp1;
          return (
            <g key={c.date}>
              <line x1={cx(i)} x2={cx(i)} y1={y(c.high)} y2={y(c.low)} stroke={col} strokeWidth={1} />
              <rect x={cx(i) - cw / 2} y={bodyTop} width={cw} height={Math.max(1, bodyBot - bodyTop)} fill={col}
                stroke={isHit ? "#ca8a04" : col} strokeWidth={isHit ? 1.5 : 0} />
              {isHit ? <text x={cx(i)} y={y(c.high) - 4} fontSize={8} textAnchor="middle" fill="#ca8a04">★</text> : null}
            </g>
          );
        })}

        {maPath(ma5, MA5C)}
        {maPath(ma10, MA10C)}

        {sigIdx >= 0 ? (
          <line x1={cx(sigIdx)} x2={cx(sigIdx)} y1={M.top} y2={M.top + plotH} stroke={ACCENT} strokeWidth={0.5} strokeDasharray="2 2" opacity={0.5} />
        ) : null}

        {level(levels.tp2, UP, "4 2", "TP2")}
        {level(levels.tp1, UP, "4 2", "TP1")}
        {level(levels.entry, ACCENT, "0", "Entry")}
        {level(levels.stop, DOWN, "4 2", "Stop")}

        {/* marker BUY: kim cương hồng ◆ tại (ngày, giá) */}
        {buyMarkers.map((mk, k) => {
          const i = idxOf.get(mk.date);
          if (i == null) return null;
          const px = cx(i);
          const py = y(mk.price);
          const r = mk.strong ? 5 : 4;
          return (
            <path key={k} d={`M ${px} ${py - r} L ${px + r} ${py} L ${px} ${py + r} L ${px - r} ${py} Z`}
              fill={BUYC} stroke="#fff" strokeWidth={1}>
              <title>{mk.date} · {mk.strong ? "STRONG BUY" : "BUY"} @ {fmt(mk.price)}</title>
            </path>
          );
        })}

        {/* crosshair khi hover */}
        {hover != null ? (
          <line x1={cx(hover)} x2={cx(hover)} y1={M.top} y2={M.top + plotH} stroke="var(--color-ink)" strokeWidth={0.5} opacity={0.35} />
        ) : null}

        {/* nhãn ngày */}
        {[...xLabels].sort((a, b) => a - b).map((i) => (
          <text key={i} x={cx(i)} y={H - 6} fontSize={8} textAnchor="middle" fill="var(--color-muted)">{candles[i].date.slice(5)}</text>
        ))}
      </svg>

      {/* Tooltip OHLC/ngày khi hover */}
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

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[10px] text-[var(--color-muted)]">
        <span><span style={{ color: MA5C }}>—</span> MA5</span>
        <span><span style={{ color: MA10C }}>—</span> MA10</span>
        <span><span style={{ color: BUYC }}>◆</span> tín hiệu BUY</span>
        <span><span style={{ color: "#ca8a04" }}>★</span> chạm TP</span>
        {hit1 ? <span className="text-[var(--color-buy)]">✓ TP1</span> : null}
        {hit2 ? <span className="text-[var(--color-buy)]">✓ TP2</span> : null}
        {hitStop ? <span className="text-[var(--color-sell)]">⚠ Stop</span> : null}
        <span className="ml-auto italic">Di chuột lên chart để xem giá/ngày.</span>
      </div>
    </div>
  );
}

// Strip intraday: giá theo từng snap trong ngày ra tín hiệu.
export function IntradayStrip({ candle }: { candle: Candle | undefined }) {
  if (!candle || candle.snaps.length < 2) {
    return <p className="text-[10px] text-[var(--color-muted)]">Ngày ra tín hiệu chỉ có 1 điểm giá — không đủ vẽ intraday.</p>;
  }
  const w = 800, h = 80, m = { l: 44, r: 60, t: 6, b: 16 };
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
