"use client";

import { useMemo, useState } from "react";
import { DecisionBadge } from "@/components/ui";
import { fmtNum, hmVN, signClass, fmtBil } from "@/lib/format";
import { CONFIDENCE_LABEL } from "@/lib/interpret";

export interface TodaySignal {
  symbol: string;
  decision: string | null;
  score_trade: number | string | null;
  snap_time: string | null;
  price: string | number | null;
  confidence: string | null;
  ff_intra_net: string | number | null;
  ff_intra_ratio: string | number | null;
  n_aligned: string | number | null;
  ff_score: string | number | null;
  fundamental_score: string | number | null;
}

/** Nhãn Quality v2.3 (dashboard html v4): khối ngoại mạnh & cơ bản tốt. */
const QUAL_FF = 5;
const QUAL_FUND = 5;
function isQuality(ff: number | null, fund: number | null): boolean {
  return ff != null && fund != null && ff >= QUAL_FF && fund >= QUAL_FUND;
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}
const isBuy = (d: string | null) => d === "BUY" || d === "STRONG BUY";

interface Snap {
  snap_time: string | null; decision: string | null; score: number | null;
  price: number | null; confidence: string | null;
  ffNet: number | null; ffRatio: number | null; nAlign: number | null;
  ffScore: number | null; fundScore: number | null;
}
interface Group {
  symbol: string; snaps: Snap[]; latest: Snap;
  nSnap: number; nBuy: number; scoreFirst: number | null; scoreLast: number | null;
}

type SortKey = "score" | "buy" | "delta";

/** Màu theo số nhóm siêu yếu tố đồng thuận (0..3): càng cao tín hiệu càng chất lượng. */
function alignColor(n: number | null): string {
  if (n == null) return "var(--color-muted)";
  if (n >= 3) return "var(--color-buy)";
  if (n >= 2) return "#ca8a04";
  return "var(--color-muted)";
}

/** Chip khối ngoại ròng luỹ kế cả phiên (chốt ở lần chạy gần nhất). */
function ForeignChip({ net, ratio }: { net: number | null; ratio: number | null }) {
  if (net == null) return null;
  const cls = net > 0 ? "text-[var(--color-buy)]" : net < 0 ? "text-[var(--color-sell)]" : "text-[var(--color-muted)]";
  const ratioTxt = ratio != null ? ` (${(ratio * 100).toFixed(0)}% GTGD)` : "";
  return (
    <span className={`tabular ${cls}`} title={`Khối ngoại ròng luỹ kế cả phiên${ratioTxt} — chốt ở lần chạy gần nhất; tham chiếu, chưa vào điểm`}>
      NN {fmtBil(net)}
    </span>
  );
}

/** Nhãn ⭐ Quality (v2.3): khối ngoại mạnh (ff≥5) & cơ bản tốt (fund≥5). */
function QualityChip({ ff, fund }: { ff: number | null; fund: number | null }) {
  if (!isQuality(ff, fund)) return null;
  return (
    <span
      className="tabular shrink-0 rounded border border-[var(--color-buy)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-buy)]"
      title={`Quality: khối ngoại mạnh (điểm FF ${ff}≥${QUAL_FF}) & cơ bản tốt (điểm cơ bản ${fund}≥${QUAL_FUND}) — thước đo v2.3`}
    >
      ⭐ Quality
    </span>
  );
}

/** Chip chất lượng: số nhóm siêu yếu tố đồng thuận. */
function AlignChip({ n }: { n: number | null }) {
  if (n == null) return null;
  const color = alignColor(n);
  return (
    <span className="tabular" style={{ color }} title="Số nhóm siêu yếu tố (xu hướng, dòng tiền, cơ bản…) cùng ủng hộ — càng cao tín hiệu càng chất lượng">
      ◆ {n}/3 nhóm
    </span>
  );
}

export function TodayBoard({ signals, totalSnaps }: { signals: TodaySignal[]; totalSnaps: number }) {
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [buyOnly, setBuyOnly] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const groups = useMemo<Group[]>(() => {
    const by = new Map<string, Snap[]>();
    for (const s of signals) {
      const arr = by.get(s.symbol) ?? [];
      arr.push({
        snap_time: s.snap_time, decision: s.decision, score: num(s.score_trade),
        price: num(s.price), confidence: s.confidence,
        ffNet: num(s.ff_intra_net), ffRatio: num(s.ff_intra_ratio), nAlign: num(s.n_aligned),
        ffScore: num(s.ff_score), fundScore: num(s.fundamental_score),
      });
      by.set(s.symbol, arr);
    }
    const out: Group[] = [];
    for (const [symbol, snaps] of by) {
      snaps.sort((a, b) => String(a.snap_time).localeCompare(String(b.snap_time)));
      const latest = snaps[snaps.length - 1];
      const nBuy = snaps.filter((x) => isBuy(x.decision)).length;
      out.push({
        symbol, snaps, latest, nSnap: snaps.length, nBuy,
        scoreFirst: snaps[0].score, scoreLast: latest.score,
      });
    }
    return out;
  }, [signals]);

  const displayed = useMemo(() => {
    const qq = q.trim().toUpperCase();
    let arr = groups.filter((g) => (!buyOnly || isBuy(g.latest.decision)) && (!qq || g.symbol.includes(qq)));
    const delta = (g: Group) => (g.scoreLast ?? 0) - (g.scoreFirst ?? 0);
    arr = [...arr].sort((a, b) => {
      if (sortKey === "buy") return b.nBuy - a.nBuy || (b.scoreLast ?? 0) - (a.scoreLast ?? 0);
      if (sortKey === "delta") return delta(b) - delta(a);
      return (b.scoreLast ?? 0) - (a.scoreLast ?? 0);
    });
    return arr;
  }, [groups, buyOnly, q, sortKey]);

  const SORT_OPTS: { key: SortKey; label: string }[] = [
    { key: "score", label: "Score ↓" },
    { key: "buy", label: "Giữ BUY nhiều ↓" },
    { key: "delta", label: "Score tăng trong ngày ↓" },
  ];

  return (
    <div className="flex flex-col gap-2">
      <div className="card flex flex-wrap items-center gap-2 p-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Tìm mã…"
          className="min-h-[38px] w-32 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2.5 py-1.5 text-sm uppercase sm:max-w-[200px]"
        />
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)} className="min-h-[38px] rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-[13px]">
          {SORT_OPTS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
        <label className="flex min-h-[38px] cursor-pointer items-center gap-1.5 text-[13px] text-[var(--color-muted)]">
          <input type="checkbox" checked={buyOnly} onChange={(e) => setBuyOnly(e.target.checked)} className="h-4 w-4" />
          Chỉ BUY
        </label>
        <span className="ml-auto text-[11px] text-[var(--color-muted)]">{displayed.length} mã · {totalSnaps} lần chạy hôm nay</span>
      </div>

      <ul className="flex flex-col gap-1.5">
        {displayed.map((g) => {
          const isOpen = open === g.symbol;
          const delta = (g.scoreLast ?? 0) - (g.scoreFirst ?? 0);
          const c = CONFIDENCE_LABEL[String(g.latest.confidence ?? "").toUpperCase()];
          const buyFrac = g.nSnap ? g.nBuy / g.nSnap : 0;
          const buyColor = buyFrac >= 0.8 ? "var(--color-buy)" : buyFrac >= 0.5 ? "#ca8a04" : "var(--color-muted)";
          return (
            <li key={g.symbol} className="card overflow-hidden">
              <button
                onClick={() => setOpen(isOpen ? null : g.symbol)}
                className="flex w-full flex-col gap-1 px-3 py-2.5 text-left active:bg-black/[0.03] dark:active:bg-white/[0.03]"
              >
                <div className="flex w-full items-center gap-2">
                  <span className="w-14 shrink-0 font-semibold">{g.symbol}</span>
                  <DecisionBadge decision={g.latest.decision} />
                  <QualityChip ff={g.latest.ffScore} fund={g.latest.fundScore} />
                  {g.nSnap > 1 && g.nBuy > 0 ? (
                    <span className="tabular shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium" style={{ color: buyColor, borderColor: buyColor }} title="Số lần chạy hôm nay mã là BUY / tổng số lần chạy">
                      BUY {g.nBuy}/{g.nSnap}
                    </span>
                  ) : null}
                  <span className="tabular ml-auto shrink-0 text-right">
                    <span className="font-semibold">{fmtNum(g.scoreLast)}</span>
                    {g.nSnap > 1 && Math.abs(delta) >= 0.01 ? (
                      <span className={`ml-1 text-[11px] ${signClass(delta)}`}>{delta > 0 ? "▲" : "▼"}{Math.abs(delta).toFixed(1)}</span>
                    ) : null}
                  </span>
                  <span aria-hidden className="shrink-0 text-[var(--color-muted)]">{isOpen ? "▴" : "▾"}</span>
                </div>
                {/* Meta: chất lượng · khối ngoại · confidence · giá — gọn, xuống dòng đẹp trên mobile */}
                <div className="flex w-full flex-wrap items-center gap-x-2.5 gap-y-0.5 pl-16 text-[11px]">
                  <AlignChip n={g.latest.nAlign} />
                  {g.latest.ffScore != null && g.latest.fundScore != null ? (
                    <span className="tabular text-[var(--color-muted)]" title="Điểm khối ngoại (FF) · điểm cơ bản — thước đo v2.3, thang ±20">
                      FF {g.latest.ffScore} · CB {g.latest.fundScore}
                    </span>
                  ) : null}
                  <ForeignChip net={g.latest.ffNet} ratio={g.latest.ffRatio} />
                  {c ? <span style={{ color: c.color }}>{c.text}</span> : null}
                  <span className="tabular text-[var(--color-muted)]">giá {fmtNum(g.latest.price)}</span>
                </div>
              </button>

              {isOpen ? (
                <div className="border-t border-[var(--color-border)] bg-black/[0.015] px-3 py-2 dark:bg-white/[0.03]">
                  <div className="mb-1 text-[11px] font-medium text-[var(--color-muted)]">Diễn biến {g.nSnap} lần chạy hôm nay (giờ VN):</div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr className="text-left text-[11px] text-[var(--color-muted)]">
                          <th className="py-1 font-medium">Giờ</th>
                          <th className="py-1 font-medium">Quyết định</th>
                          <th className="py-1 text-right font-medium">Score</th>
                          <th className="py-1 text-right font-medium">Giá</th>
                          <th className="py-1 text-right font-medium" title="Khối ngoại ròng luỹ kế trong phiên tính đến giờ đó — dòng cuối = tổng cả phiên (KHÔNG cộng dồn giữa các dòng)">NN luỹ kế</th>
                        </tr>
                      </thead>
                      <tbody>
                        {g.snaps.map((s, i) => {
                          const prev = i > 0 ? g.snaps[i - 1].decision : null;
                          const changed = prev != null && prev !== s.decision;
                          const ffCls = s.ffNet == null ? "text-[var(--color-muted)]" : s.ffNet > 0 ? "text-[var(--color-buy)]" : s.ffNet < 0 ? "text-[var(--color-sell)]" : "text-[var(--color-muted)]";
                          return (
                            <tr key={i} className="border-t border-[var(--color-border)]/60">
                              <td className="py-1 tabular whitespace-nowrap">{hmVN(s.snap_time)}</td>
                              <td className="py-1"><span className="inline-flex items-center gap-1"><DecisionBadge decision={s.decision} />{changed ? <span className="text-[10px] text-[var(--color-accent)]">↳ đổi</span> : null}</span></td>
                              <td className="py-1 text-right tabular">{fmtNum(s.score)}</td>
                              <td className="py-1 text-right tabular text-[var(--color-muted)]">{fmtNum(s.price)}</td>
                              <td className={`py-1 text-right tabular whitespace-nowrap ${ffCls}`}>{fmtBil(s.ffNet)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-1.5 text-[10px] text-[var(--color-muted)]">
                    NN luỹ kế = khối ngoại ròng cộng dồn trong phiên đến giờ đó; dòng cuối = tổng cả phiên (các dòng KHÔNG cộng lại với nhau) · tham chiếu, chưa vào điểm.
                  </p>
                </div>
              ) : null}
            </li>
          );
        })}
        {displayed.length === 0 ? <li className="card px-3 py-6 text-center text-sm text-[var(--color-muted)]">Không có mã khớp.</li> : null}
      </ul>
    </div>
  );
}
