import type { Candle, Levels } from "@/lib/chart";
import { tpHit } from "@/lib/chart";

// Chart nến custom SVG. Responsive qua viewBox. Màu semantic: lên xanh, xuống đỏ.
// Overlay: entry (accent), stop (đỏ đứt), tp1/tp2 (xanh đứt). ★ = nến chạm TP.

const W = 780;
const H = 340;
const M = { top: 14, right: 62, bottom: 26, left: 46 };

const UP = "#16a34a";
const DOWN = "#dc2626";
const ACCENT = "#2563eb";

function fmt(n: number): string {
  return n.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function PriceChart({ candles, levels }: { candles: Candle[]; levels: Levels }) {
  if (!candles.length) {
    return <p className="p-6 text-sm text-[var(--color-muted)]">Chưa đủ dữ liệu giá để vẽ.</p>;
  }

  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;

  // Y domain gồm cả nến + các mức.
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
  const cw = Math.max(2, Math.min(14, slot * 0.6));
  const cx = (i: number) => M.left + slot * (i + 0.5);

  const { hit1, hit2, hitStop } = tpHit(candles, levels);

  // Nhãn Y (5 mốc)
  const yTicks = Array.from({ length: 5 }, (_, k) => yMin + ((yMax - yMin) * k) / 4);

  // Nhãn X: đầu, ngày tín hiệu, cuối
  const sigIdx = candles.findIndex((c) => c.date >= levels.signalDate);
  const xLabels = new Set([0, n - 1]);
  if (sigIdx >= 0) xLabels.add(sigIdx);

  function level(v: number | null, color: string, dash: string, label: string) {
    if (v == null) return null;
    const yy = y(v);
    return (
      <g>
        <line x1={M.left} x2={M.left + plotW} y1={yy} y2={yy} stroke={color} strokeWidth={1} strokeDasharray={dash} opacity={0.9} />
        <text x={M.left + plotW + 4} y={yy + 3} fontSize={10} fill={color} className="tabular">
          {label} {fmt(v)}
        </text>
      </g>
    );
  }

  return (
    <div className="w-full overflow-hidden">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Chart giá">
        {/* gridlines + nhãn Y */}
        {yTicks.map((t, k) => (
          <g key={k}>
            <line x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--color-border)" strokeWidth={0.5} />
            <text x={M.left - 6} y={y(t) + 3} fontSize={10} textAnchor="end" fill="var(--color-muted)" className="tabular">
              {fmt(t)}
            </text>
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
              <rect
                x={cx(i) - cw / 2}
                y={bodyTop}
                width={cw}
                height={Math.max(1, bodyBot - bodyTop)}
                fill={col}
                stroke={isHit ? "#ca8a04" : col}
                strokeWidth={isHit ? 1.5 : 0}
              />
              {isHit ? (
                <text x={cx(i)} y={y(c.high) - 4} fontSize={9} textAnchor="middle" fill="#ca8a04">★</text>
              ) : null}
            </g>
          );
        })}

        {/* vạch ngày tín hiệu */}
        {sigIdx >= 0 ? (
          <line x1={cx(sigIdx)} x2={cx(sigIdx)} y1={M.top} y2={M.top + plotH} stroke={ACCENT} strokeWidth={0.5} strokeDasharray="2 2" opacity={0.6} />
        ) : null}

        {/* các mức */}
        {level(levels.tp2, UP, "4 2", "TP2")}
        {level(levels.tp1, UP, "4 2", "TP1")}
        {level(levels.entry, ACCENT, "0", "Entry")}
        {level(levels.stop, DOWN, "4 2", "Stop")}

        {/* marker entry */}
        {levels.entry != null && sigIdx >= 0 ? (
          <circle cx={cx(sigIdx)} cy={y(levels.entry)} r={3.5} fill={ACCENT} stroke="#fff" strokeWidth={1} />
        ) : null}

        {/* nhãn X */}
        {[...xLabels].sort((a, b) => a - b).map((i) => (
          <text key={i} x={cx(i)} y={H - 8} fontSize={9} textAnchor="middle" fill="var(--color-muted)">
            {candles[i].date.slice(5)}
          </text>
        ))}
      </svg>

      <div className="mt-1 flex flex-wrap gap-3 px-1 text-[11px] text-[var(--color-muted)]">
        <span>★ chạm TP</span>
        {hit1 ? <span className="text-[var(--color-buy)]">✓ đã chạm TP1</span> : null}
        {hit2 ? <span className="text-[var(--color-buy)]">✓ đã chạm TP2</span> : null}
        {hitStop ? <span className="text-[var(--color-sell)]">⚠ đã chạm Stop</span> : null}
        <span className="ml-auto italic">Nến dựng từ giá snap — không phải tick OHLC đầy đủ.</span>
      </div>
    </div>
  );
}

// Strip intraday: giá theo từng snap trong 1 ngày (ngày ra tín hiệu).
export function IntradayStrip({ candle }: { candle: Candle | undefined }) {
  if (!candle || candle.snaps.length < 2) {
    return <p className="text-xs text-[var(--color-muted)]">Ngày ra tín hiệu chỉ có 1 điểm giá — không đủ vẽ intraday.</p>;
  }
  const w = 780, h = 90, m = { l: 46, r: 62, t: 8, b: 18 };
  const pw = w - m.l - m.r, ph = h - m.t - m.b;
  const prices = candle.snaps.map((s) => s.price);
  let lo = Math.min(...prices), hi = Math.max(...prices);
  const pad = (hi - lo) * 0.15 || hi * 0.01 || 0.5;
  lo -= pad; hi += pad;
  const n = candle.snaps.length;
  const x = (i: number) => m.l + (n === 1 ? pw / 2 : (pw * i) / (n - 1));
  const y = (v: number) => m.t + ph - ((v - lo) / (hi - lo)) * ph;
  const up = prices[n - 1] >= prices[0];
  const col = up ? UP : DOWN;
  const pts = candle.snaps.map((s, i) => `${x(i)},${y(s.price)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label="Giá intraday ngày ra tín hiệu">
      <polyline points={pts} fill="none" stroke={col} strokeWidth={1.5} />
      {candle.snaps.map((s, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(s.price)} r={2.5} fill={col} />
          <text x={x(i)} y={h - 5} fontSize={9} textAnchor="middle" fill="var(--color-muted)">{s.t}</text>
        </g>
      ))}
      <text x={m.l - 6} y={y(hi) + 8} fontSize={9} textAnchor="end" fill="var(--color-muted)" className="tabular">{fmt(hi)}</text>
      <text x={m.l - 6} y={y(lo) + 3} fontSize={9} textAnchor="end" fill="var(--color-muted)" className="tabular">{fmt(lo)}</text>
    </svg>
  );
}
