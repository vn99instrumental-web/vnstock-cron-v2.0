"use client";

import { useMemo, useState } from "react";
import { DecisionBadge } from "@/components/ui";
import { fmtNum, snapHM, signClass } from "@/lib/format";
import { CONFIDENCE_LABEL } from "@/lib/interpret";

export interface TodaySignal {
  symbol: string;
  decision: string | null;
  score_trade: number | string | null;
  snap_time: string | null;
  price: string | number | null;
  confidence: string | null;
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}
const isBuy = (d: string | null) => d === "BUY" || d === "STRONG BUY";

interface Snap { snap_time: string | null; decision: string | null; score: number | null; price: number | null; confidence: string | null }
interface Group {
  symbol: string; snaps: Snap[]; latest: Snap;
  nSnap: number; nBuy: number; scoreFirst: number | null; scoreLast: number | null;
}

type SortKey = "score" | "buy" | "delta";

export function TodayBoard({ signals, totalSnaps }: { signals: TodaySignal[]; totalSnaps: number }) {
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [buyOnly, setBuyOnly] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const groups = useMemo<Group[]>(() => {
    const by = new Map<string, Snap[]>();
    for (const s of signals) {
      const arr = by.get(s.symbol) ?? [];
      arr.push({ snap_time: s.snap_time, decision: s.decision, score: num(s.score_trade), price: num(s.price), confidence: s.confidence });
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
                className="flex w-full items-center gap-2 px-3 py-2.5 text-left active:bg-black/[0.03] dark:active:bg-white/[0.03]"
              >
                <span className="w-14 shrink-0 font-semibold">{g.symbol}</span>
                <DecisionBadge decision={g.latest.decision} />
                {c ? <span className="hidden text-[11px] sm:inline" style={{ color: c.color }}>{c.text}</span> : null}
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
                <span className="tabular hidden w-16 shrink-0 text-right text-[13px] text-[var(--color-muted)] sm:inline">{fmtNum(g.latest.price)}</span>
                <span aria-hidden className="shrink-0 text-[var(--color-muted)]">{isOpen ? "▴" : "▾"}</span>
              </button>

              {isOpen ? (
                <div className="border-t border-[var(--color-border)] bg-black/[0.015] px-3 py-2 dark:bg-white/[0.03]">
                  <div className="mb-1 text-[11px] font-medium text-[var(--color-muted)]">Diễn biến {g.nSnap} lần chạy hôm nay:</div>
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr className="text-left text-[11px] text-[var(--color-muted)]">
                        <th className="py-1 font-medium">Giờ</th>
                        <th className="py-1 font-medium">Quyết định</th>
                        <th className="py-1 text-right font-medium">Score</th>
                        <th className="py-1 text-right font-medium">Giá</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.snaps.map((s, i) => {
                        const prev = i > 0 ? g.snaps[i - 1].decision : null;
                        const changed = prev != null && prev !== s.decision;
                        return (
                          <tr key={i} className="border-t border-[var(--color-border)]/60">
                            <td className="py-1 tabular">{snapHM(s.snap_time)}</td>
                            <td className="py-1"><span className="inline-flex items-center gap-1"><DecisionBadge decision={s.decision} />{changed ? <span className="text-[10px] text-[var(--color-accent)]">↳ đổi</span> : null}</span></td>
                            <td className="py-1 text-right tabular">{fmtNum(s.score)}</td>
                            <td className="py-1 text-right tabular text-[var(--color-muted)]">{fmtNum(s.price)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <p className="mt-1.5 text-[10px] italic text-[var(--color-muted)]">
                    {g.nBuy === g.nSnap && isBuy(g.latest.decision)
                      ? "✓ Giữ BUY suốt cả ngày — tín hiệu bền."
                      : g.nBuy > 0
                        ? `BUY ${g.nBuy}/${g.nSnap} lần — có lúc đổi quyết định, đọc kỹ diễn biến.`
                        : "Không có tín hiệu BUY hôm nay."}
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
