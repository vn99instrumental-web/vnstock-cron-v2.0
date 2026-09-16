"use client";

// Biểu đồ dòng thời gian tín hiệu cho 1 mã: mỗi cột = 1 tín hiệu.
// Cao/thấp so với trục 0 = lãi 5 phiên; màu = kết quả (chạm TP / SL / chưa chạm).
// STRONG BUY có viền đậm. Hover xem chi tiết.

export interface TimelineRow {
  pred_id: string;
  signal_date: string;
  decision: string | null;
  confidence: string | null;
  ret_5d: number | string | null;
  mfe_pct: number | string | null;
  mae_pct: number | string | null;
  std_outcome: string | null;
  std3_outcome: string | null;
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}
function outColor(o: string | null): string {
  if (o == null) return "var(--color-muted)";
  if (o.startsWith("tp")) return "var(--color-buy)";
  if (o === "sl") return "var(--color-sell)";
  return "#9ca3af"; // open: xám
}
function outLabel(o: string | null): string {
  if (o == null) return "chờ chín";
  if (o.startsWith("tp")) return "chạm TP";
  if (o === "sl") return "chạm SL";
  return "chưa chạm";
}

export function SignalTimeline({ rows, target }: { rows: TimelineRow[]; target: "std_outcome" | "std3_outcome" }) {
  if (!rows.length) return <div className="py-6 text-center text-[11px] text-[var(--color-muted)]">Chưa có tín hiệu.</div>;

  const rets = rows.map((r) => num(r.ret_5d) ?? 0);
  const D = Math.max(4, Math.ceil(Math.max(...rets.map(Math.abs), 4)));
  const step = 54;
  const mL = 34, mR = 14, mT = 20, mB = 36;
  const plotH = 132;
  const W = mL + mR + rows.length * step;
  const H = mT + plotH + mB;
  const y0 = mT + plotH / 2; // trục 0 ở giữa (miền đối xứng ±D)
  const yOf = (v: number) => y0 - (v / D) * (plotH / 2);
  const barW = 16;

  const gridVals = [D, D / 2, 0, -D / 2, -D];

  return (
    <div className="overflow-x-auto">
      <svg width={W} height={H} role="img" style={{ maxWidth: "none" }}>
        {/* lưới + nhãn trục y */}
        {gridVals.map((g) => (
          <g key={g}>
            <line x1={mL} y1={yOf(g)} x2={W - mR} y2={yOf(g)} stroke="var(--color-border)" strokeWidth={g === 0 ? 1.2 : 0.6} strokeDasharray={g === 0 ? "" : "3 3"} />
            <text x={mL - 4} y={yOf(g) + 3} textAnchor="end" fontSize={8} fill="var(--color-muted)" className="tabular">{g > 0 ? "+" : ""}{g}%</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const o = r[target];
          const ret = num(r.ret_5d) ?? 0;
          const cx = mL + i * step + step / 2;
          const vy = yOf(ret);
          const color = outColor(o);
          const strong = r.decision === "STRONG BUY";
          const top = Math.min(y0, vy);
          const h = Math.abs(vy - y0);
          const mfe = num(r.mfe_pct), mae = num(r.mae_pct);
          return (
            <g key={r.pred_id}>
              <title>{`${r.signal_date} · ${r.decision} · ${outLabel(o)}\nlãi 5 phiên: ${ret.toFixed(1)}%  ·  MFE ${mfe != null ? "+" + mfe.toFixed(1) : "—"}% / MAE ${mae != null ? mae.toFixed(1) : "—"}%`}</title>
              <rect x={cx - barW / 2} y={top} width={barW} height={Math.max(1, h)} rx={2} fill={color} opacity={o == null ? 0.4 : 0.85} />
              <circle cx={cx} cy={vy} r={strong ? 5 : 3.5} fill={color} stroke={strong ? "var(--color-ink)" : "#fff"} strokeWidth={strong ? 1.5 : 1} />
              <text x={cx} y={ret >= 0 ? vy - 7 : vy + 12} textAnchor="middle" fontSize={8} fontWeight={600} fill={color} className="tabular">{ret >= 0 ? "+" : ""}{ret.toFixed(1)}</text>
              <text x={cx} y={H - 20} textAnchor="middle" fontSize={8} fill="var(--color-muted)">{r.signal_date.slice(5)}</text>
              {strong ? <text x={cx} y={H - 8} textAnchor="middle" fontSize={7} fill="var(--color-muted)">★SBUY</text> : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
