"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { buildCandles, type Candle, type Levels, type PricePoint } from "@/lib/chart";
import { PriceChart, IntradayStrip } from "@/components/price-chart";
import { DecisionBadge } from "@/components/ui";
import { fmtNum } from "@/lib/format";

export interface BuySignal {
  id: number;
  symbol: string;
  decision: string | null;
  score_trade: number | null;
  signal_date: string;
  breakdown: Record<string, unknown> | null;
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

export function BuyBoard({ signals }: { signals: BuySignal[] }) {
  const [sel, setSel] = useState<BuySignal | null>(signals[0] ?? null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sel) return;
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const supabase = createClient();
        const { data } = await supabase
          .from("v4_signals")
          .select("signal_date, snap_time, price:breakdown->>price")
          .eq("symbol", sel.symbol)
          .order("signal_date", { ascending: true })
          .order("snap_time", { ascending: true });
        if (!alive) return;
        const points: PricePoint[] = (data ?? [])
          .map((r: Record<string, unknown>) => ({
            signal_date: String(r.signal_date),
            snap_time: String(r.snap_time),
            price: num(r.price) ?? NaN,
          }))
          .filter((p) => Number.isFinite(p.price));
        setCandles(buildCandles(points));
      } catch {
        if (alive) setCandles([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [sel]);

  const levels: Levels | null = useMemo(() => {
    if (!sel) return null;
    const b = sel.breakdown ?? {};
    return {
      entry: num(b.entry),
      stop: num(b.stop),
      tp1: num(b.tp1),
      tp2: num(b.tp2),
      signalDate: sel.signal_date,
    };
  }, [sel]);

  const entryCandle = candles.find((c) => c.date === sel?.signal_date);

  if (!signals.length) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--color-border)] px-6 py-12 text-center text-sm text-[var(--color-muted)]">
        Run mới nhất chưa có mã BUY/STRONG BUY.
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-[260px_1fr]">
      {/* LIST trái */}
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-3 py-2 text-xs font-medium text-[var(--color-muted)]">
          {signals.length} mã BUY / STRONG BUY
        </div>
        <ul className="max-h-[70vh] overflow-y-auto">
          {signals.map((s) => {
            const active = sel?.id === s.id;
            return (
              <li key={s.id}>
                <button
                  onClick={() => setSel(s)}
                  className={`flex w-full items-center justify-between gap-2 border-b border-[var(--color-border)] px-3 py-2 text-left text-sm ${
                    active ? "bg-[var(--color-accent)]/10" : "hover:bg-black/[0.03] dark:hover:bg-white/[0.03]"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span className="font-semibold">{s.symbol}</span>
                    <DecisionBadge decision={s.decision} />
                  </span>
                  <span className="tabular text-xs text-[var(--color-muted)]">{fmtNum(s.score_trade)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {/* DETAIL phải */}
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        {sel && levels ? (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1">
              <h2 className="text-base font-semibold">{sel.symbol}</h2>
              <DecisionBadge decision={sel.decision} />
              <span className="text-xs text-[var(--color-muted)]">
                tín hiệu {sel.signal_date} · score {fmtNum(sel.score_trade)}
              </span>
              <div className="ml-auto flex flex-wrap gap-x-3 text-xs tabular">
                <span>Entry <b>{levels.entry != null ? fmtNum(levels.entry) : "—"}</b></span>
                <span className="text-[var(--color-sell)]">Stop {levels.stop != null ? fmtNum(levels.stop) : "—"}</span>
                <span className="text-[var(--color-buy)]">TP1 {levels.tp1 != null ? fmtNum(levels.tp1) : "—"}</span>
                <span className="text-[var(--color-buy)]">TP2 {levels.tp2 != null ? fmtNum(levels.tp2) : "—"}</span>
              </div>
            </div>

            {loading ? (
              <div className="grid h-[300px] place-items-center text-sm text-[var(--color-muted)]">Đang tải giá…</div>
            ) : (
              <>
                <PriceChart candles={candles} levels={levels} />
                <div className="mt-4">
                  <div className="mb-1 text-xs font-medium text-[var(--color-muted)]">
                    Giá trong ngày ra tín hiệu ({sel.signal_date}) — theo từng lần chạy intraday
                  </div>
                  <IntradayStrip candle={entryCandle} />
                </div>
              </>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
