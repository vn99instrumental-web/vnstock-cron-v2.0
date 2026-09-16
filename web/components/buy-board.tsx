"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { buildCandles, type Candle, type Levels, type PricePoint } from "@/lib/chart";
import { PriceChart, IntradayStrip, type BuyMarker } from "@/components/price-chart";
import { DecisionBadge } from "@/components/ui";
import { fmtNum, fmtPct, signClass } from "@/lib/format";
import {
  factorViews, signalViews, CONFIDENCE_LABEL, DIR_COLOR, DIR_LABEL,
} from "@/lib/interpret";

export interface BuySignal {
  id: number;
  symbol: string;
  decision: string | null;
  score_trade: number | null;
  signal_date: string;
  breakdown: Record<string, unknown> | null;
  changePct?: number | null; // % vs giá TC (phiên trước), tính ở server
}

export interface ExpectancyRow {
  decision: string;
  confidence: string;
  n: number;
  avg_ret_1d: number | string | null;
  avg_ret_5d: number | string | null;
  avg_ret_10d: number | string | null;
  avg_mfe: number | string | null;
  avg_mae: number | string | null;
  winrate_5d: number | string | null;
}

// D/E/F — độ vững tín hiệu theo mã (view v4_buy_robustness).
export interface RobustnessRow {
  symbol: string;
  total_days_15d: number | string | null;
  buy_days_15d: number | string | null;
  total_snaps_today: number | string | null;
  buy_snaps_today: number | string | null;
  first_buy_snap_vn: string | null;
}

type SortKey = "score" | "chg_desc" | "chg_asc" | "ff_desc" | "ff_asc" | "adtv_desc" | "persist_desc";
const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "score", label: "Score ↓" },
  { key: "persist_desc", label: "Bền tín hiệu ↓" },
  { key: "adtv_desc", label: "Thanh khoản ↓" },
  { key: "chg_desc", label: "% tăng nhiều ↓" },
  { key: "chg_asc", label: "% giảm nhiều ↑" },
  { key: "ff_desc", label: "Khối ngoại MUA ↓" },
  { key: "ff_asc", label: "Khối ngoại BÁN ↑" },
];

/** ADTV (thanh khoản, tỷ VND) từ breakdown.adtv_bil. */
function adtvOf(s: BuySignal): number | null {
  const v = Number((s.breakdown ?? {}).adtv_bil);
  return Number.isFinite(v) ? v : null;
}

/** Phân loại thanh khoản cho mua ngắn hạn (tỷ VND/phiên). */
function liqTier(adtv: number | null): { label: string; color: string; warn: boolean } | null {
  if (adtv == null) return { label: "KL ?", color: "var(--color-muted)", warn: false };
  if (adtv < 3) return { label: `${adtv.toFixed(1)} tỷ · rất mỏng`, color: "var(--color-sell)", warn: true };
  if (adtv < 10) return { label: `${adtv.toFixed(1)} tỷ · mỏng`, color: "#ca8a04", warn: true };
  return { label: `${adtv.toFixed(adtv < 100 ? 1 : 0)} tỷ`, color: "var(--color-buy)", warn: false };
}

/** Badge thanh khoản (D). */
function LiqBadge({ adtv }: { adtv: number | null }) {
  const t = liqTier(adtv);
  if (!t) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium"
      style={{ color: t.color, borderColor: t.color }}
      title="Thanh khoản TB (giá trị khớp/phiên). Dưới ~10 tỷ khó vào/ra nhanh, dễ trượt giá khi mua ngắn hạn."
    >
      ⚡ {t.label}
    </span>
  );
}

/** Màu theo tỷ lệ giữ BUY: cao = xanh, thấp = xám/vàng. */
function robColor(frac: number): string {
  if (frac >= 0.8) return "var(--color-buy)";
  if (frac >= 0.5) return "#ca8a04";
  return "var(--color-muted)";
}

/** E — độ bền qua phiên. Badge gọn cho list. */
function PersistChip({ r }: { r: RobustnessRow | undefined }) {
  if (!r) return null;
  const bd = Number(r.buy_days_15d) || 0;
  const td = Number(r.total_days_15d) || 0;
  if (!td) return null;
  return (
    <span
      className="tabular text-[10px] font-medium"
      style={{ color: robColor(bd / td) }}
      title={`Giữ tín hiệu BUY ${bd}/${td} phiên gần đây. Càng nhiều phiên liên tục càng bền, ít "nháy 1 lần".`}
    >
      bền {bd}/{td}
    </span>
  );
}

/** VND → "x.x tỷ" / "x triệu". */
function fmtBil(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const b = v / 1e9;
  if (Math.abs(b) >= 0.1) return (b >= 0 ? "+" : "") + b.toFixed(1) + " tỷ";
  return (v >= 0 ? "+" : "") + (v / 1e6).toFixed(0) + " tr";
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

function ConfChip({ conf, withLabel = false }: { conf: unknown; withLabel?: boolean }) {
  const key = String(conf ?? "").toUpperCase();
  const c = CONFIDENCE_LABEL[key];
  if (!c) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium"
      style={{ color: c.color, borderColor: c.color }}
      title="Chất lượng tín hiệu (confidence)"
    >
      <span aria-hidden style={{ width: 6, height: 6, borderRadius: 9, background: c.color }} />
      {withLabel ? "Chất lượng: " : ""}{c.text}
    </span>
  );
}

function agoText(min: number): string {
  if (min < 1) return "vừa xong";
  if (min < 60) return `${min} phút trước`;
  const h = Math.floor(min / 60);
  return h < 24 ? `${h} giờ trước` : `${Math.floor(h / 24)} ngày trước`;
}

export function BuyBoard({
  signals,
  expectancy = [],
  robustness = [],
  runId,
  runStartedAt = null,
  newestRunId = null,
}: {
  signals: BuySignal[];
  expectancy?: ExpectancyRow[];
  robustness?: RobustnessRow[];
  runId?: string;
  runStartedAt?: string | null;
  newestRunId?: string | null;
}) {
  const robMap = useMemo(
    () => new Map(robustness.map((r) => [r.symbol, r])),
    [robustness],
  );
  const [sel, setSel] = useState<BuySignal | null>(signals[0] ?? null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [markers, setMarkers] = useState<BuyMarker[]>([]);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [showList, setShowList] = useState(true);
  const [hideThin, setHideThin] = useState(false); // D — ẩn mã thanh khoản < 10 tỷ

  useEffect(() => {
    if (!sel) return;
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const supabase = createClient();
        // Song song: snaps (marker BUY + intraday + fallback) và OHLC thật (nến daily có lịch sử).
        const [sigRes, ohlcRes] = await Promise.all([
          supabase
            .from("v4_signals")
            .select("signal_date, snap_time, decision, price:breakdown->>price")
            .eq("symbol", sel.symbol)
            .order("signal_date", { ascending: true })
            .order("snap_time", { ascending: true }),
          supabase
            .from("v4_ohlc")
            .select("date, open, high, low, close")
            .eq("symbol", sel.symbol)
            .order("date", { ascending: true }),
        ]);
        if (!alive) return;
        const rows = (sigRes.data ?? []) as Record<string, unknown>[];
        const points: PricePoint[] = rows
          .map((r) => ({ signal_date: String(r.signal_date), snap_time: String(r.snap_time), price: num(r.price) ?? NaN }))
          .filter((p) => Number.isFinite(p.price));
        const snapCandles = buildCandles(points);
        const snapMap = new Map(snapCandles.map((c) => [c.date, c.snaps]));

        const ohlc = (ohlcRes.data ?? []) as Record<string, unknown>[];
        let finalCandles: Candle[];
        if (ohlc.length) {
          // Nến thật từ v4_ohlc; đính kèm snaps cùng ngày (cho strip intraday).
          finalCandles = ohlc
            .map((r) => {
              const o = num(r.open), h = num(r.high), l = num(r.low), c = num(r.close);
              if (o == null || h == null || l == null || c == null) return null;
              const date = String(r.date);
              return { date, open: o, high: h, low: l, close: c, snaps: snapMap.get(date) ?? [] } as Candle;
            })
            .filter((x): x is Candle => x !== null);
        } else {
          finalCandles = snapCandles; // fallback: nến từ snap
        }
        setCandles(finalCandles);
        setMarkers(
          rows
            .filter((r) => r.decision === "BUY" || r.decision === "STRONG BUY")
            .map((r) => ({ date: String(r.signal_date), price: num(r.price) ?? NaN, strong: r.decision === "STRONG BUY" }))
            .filter((m) => Number.isFinite(m.price)),
        );
      } catch {
        if (alive) { setCandles([]); setMarkers([]); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [sel]);

  const levels: Levels | null = useMemo(() => {
    if (!sel) return null;
    const b = sel.breakdown ?? {};
    return { entry: num(b.entry), stop: num(b.stop), tp1: num(b.tp1), tp2: num(b.tp2), signalDate: sel.signal_date };
  }, [sel]);

  const ffNum = (s: BuySignal): number | null => {
    const v = Number((s.breakdown ?? {}).ff_intra_net);
    return Number.isFinite(v) ? v : null;
  };
  // E+F gộp thành 1 điểm bền để sort: ưu tiên số phiên giữ BUY, rồi số snap hôm nay.
  const persistScore = (s: BuySignal): number | null => {
    const r = robMap.get(s.symbol);
    if (!r) return null;
    const days = Number(r.buy_days_15d) || 0;
    const snaps = Number(r.buy_snaps_today) || 0;
    return days * 10 + snaps;
  };
  const displayed = useMemo(() => {
    const qq = q.trim().toUpperCase();
    let arr = qq ? signals.filter((s) => s.symbol.includes(qq)) : [...signals];
    if (hideThin) arr = arr.filter((s) => { const a = adtvOf(s); return a == null || a >= 10; });
    const cmpNull = (a: number | null, b: number | null, dir: 1 | -1) => {
      if (a == null && b == null) return 0;
      if (a == null) return 1; // null xuống cuối
      if (b == null) return -1;
      return (a - b) * dir;
    };
    arr.sort((a, b) => {
      switch (sortKey) {
        case "chg_desc": return cmpNull(a.changePct ?? null, b.changePct ?? null, -1);
        case "chg_asc": return cmpNull(a.changePct ?? null, b.changePct ?? null, 1);
        case "ff_desc": return cmpNull(ffNum(a), ffNum(b), -1);
        case "ff_asc": return cmpNull(ffNum(a), ffNum(b), 1);
        case "adtv_desc": return cmpNull(adtvOf(a), adtvOf(b), -1);
        case "persist_desc": return cmpNull(persistScore(a), persistScore(b), -1);
        default: return cmpNull(a.score_trade ?? null, b.score_trade ?? null, -1);
      }
    });
    return arr;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signals, q, sortKey, hideThin, robMap]);

  const entryCandle = candles.find((c) => c.date === sel?.signal_date);
  const b = sel?.breakdown ?? {};
  const factors = useMemo(() => factorViews(b), [b]);
  const sigs = useMemo(() => signalViews(b), [b]);
  const buyDays = new Set(markers.map((m) => m.date)).size;

  // C — độ tươi dữ liệu.
  const fresh = (() => {
    if (!runStartedAt) return null;
    const ageMin = Math.max(0, Math.round((Date.now() - new Date(runStartedAt).getTime()) / 60000));
    const ict = new Date(Date.now() + 7 * 3600e3);
    const dow = ict.getUTCDay();
    const hh = ict.getUTCHours() + ict.getUTCMinutes() / 60;
    const marketOpen = dow >= 1 && dow <= 5 && hh >= 9 && hh <= 15;
    return { ageMin, marketOpen, stale: marketOpen && ageMin > 30 };
  })();
  const runStale = !!newestRunId && !!runId && newestRunId !== runId;

  // A/B — kỳ vọng lịch sử theo (decision, confidence).
  const expLookup = (dec: string | null, conf: unknown): ExpectancyRow | null => {
    const c = String(conf ?? "").toUpperCase();
    return (
      expectancy.find((e) => e.decision === dec && e.confidence === c) ||
      expectancy.find((e) => e.decision === "BUY" && e.confidence === c) ||
      null
    );
  };
  const exp = sel ? expLookup(sel.decision, (sel.breakdown ?? {}).confidence) : null;
  const num = (v: unknown) => { const x = Number(v); return Number.isFinite(x) ? x : null; };

  if (!signals.length) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--color-border)] px-6 py-12 text-center text-sm text-[var(--color-muted)]">
        Run mới nhất chưa có mã BUY/STRONG BUY.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* C — thanh độ tươi dữ liệu */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-[11px]">
        <span className="font-medium">Run {runId ?? "—"}</span>
        {fresh ? (
          <span className={fresh.stale ? "font-medium text-[var(--color-sell)]" : "text-[var(--color-muted)]"}>
            cập nhật {agoText(fresh.ageMin)} · {fresh.marketOpen ? "phiên ĐANG MỞ" : "ngoài phiên"}
            {fresh.stale ? " ⚠ data có thể trễ" : ""}
          </span>
        ) : null}
        {runStale ? (
          <span className="text-[var(--color-sell)]">⚠ có run mới hơn ({newestRunId}) chưa đủ BUY — đang xem run có BUY gần nhất</span>
        ) : null}
        <span className="ml-auto italic text-[var(--color-muted)]">Snapshot 5×/ngày · không realtime</span>
      </div>

      <div className={showList ? "grid gap-3 md:grid-cols-[300px_1fr]" : "block"}>
      {/* LIST trái */}
      <div className={`rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] ${showList ? "" : "hidden"}`}>
        <div className="flex items-center gap-1.5 border-b border-[var(--color-border)] p-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Tìm mã…"
            className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-xs uppercase"
          />
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-1 py-1 text-[11px]"
            title="Sắp xếp"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>{o.label}</option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-1.5 border-b border-[var(--color-border)] px-2.5 py-1 text-[10px] text-[var(--color-muted)] cursor-pointer">
          <input type="checkbox" checked={hideThin} onChange={(e) => setHideThin(e.target.checked)} className="h-3 w-3" />
          Ẩn mã thanh khoản &lt; 10 tỷ/phiên
        </label>
        <div className="px-2.5 py-1 text-[10px] text-[var(--color-muted)]">
          {displayed.length}/{signals.length} mã · %so giá TC · ⚡ thanh khoản · bền = số phiên giữ BUY · KN = khối ngoại ròng
        </div>
        <ul className="max-h-[70vh] overflow-y-auto">
          {displayed.map((s) => {
            const active = sel?.id === s.id;
            const chg = s.changePct;
            const ff = ffNum(s);
            return (
              <li key={s.id}>
                <button
                  onClick={() => setSel(s)}
                  className={`flex w-full flex-col gap-0.5 border-b border-[var(--color-border)] px-2.5 py-1.5 text-left ${
                    active ? "bg-[var(--color-accent)]/10" : "hover:bg-black/[0.03] dark:hover:bg-white/[0.03]"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-1.5 text-xs">
                    <span className="font-semibold">{s.symbol}</span>
                    <DecisionBadge decision={s.decision} />
                    <ConfChip conf={(s.breakdown ?? {}).confidence} />
                    <span className="tabular ml-auto text-[10px] text-[var(--color-muted)]">score {fmtNum(s.score_trade)}</span>
                  </span>
                  <span className="flex items-center gap-2 text-[11px] tabular">
                    <span>{fmtNum((s.breakdown ?? {}).price)}</span>
                    <span className={signClass(chg)}>{chg == null ? "—" : fmtPct(chg)}</span>
                    <span className="ml-auto" title="Khối ngoại ròng phiên (mua−bán)" style={{ color: ff == null ? "var(--color-muted)" : ff >= 0 ? "var(--color-buy)" : "var(--color-sell)" }}>
                      KN {fmtBil(ff)}
                    </span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <LiqBadge adtv={adtvOf(s)} />
                    <PersistChip r={robMap.get(s.symbol)} />
                  </span>
                </button>
              </li>
            );
          })}
          {displayed.length === 0 ? (
            <li className="px-2.5 py-4 text-center text-xs text-[var(--color-muted)]">Không có mã khớp “{q}”.</li>
          ) : null}
        </ul>
      </div>

      {/* DETAIL phải */}
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
        {sel && levels ? (
          <>
            <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <button
                onClick={() => setShowList((v) => !v)}
                title={showList ? "Ẩn danh sách (mở rộng chart)" : "Hiện danh sách"}
                className="rounded border border-[var(--color-border)] px-1.5 py-0.5 text-xs text-[var(--color-muted)] hover:text-[var(--color-ink)]"
              >
                {showList ? "‹ Ẩn DS" : "☰ DS"}
              </button>
              <h2 className="text-sm font-semibold">{sel.symbol}</h2>
              <DecisionBadge decision={sel.decision} />
              <ConfChip conf={b.confidence} withLabel />
              <span className="text-[11px] text-[var(--color-muted)]">
                tín hiệu {sel.signal_date} · score {fmtNum(sel.score_trade)}
                {buyDays > 1 ? ` · ${buyDays} ngày có tín hiệu BUY` : ""}
              </span>
              <div className="ml-auto flex flex-wrap gap-x-2.5 text-[11px] tabular">
                <span>Entry <b>{levels.entry != null ? fmtNum(levels.entry) : "—"}</b></span>
                {levels.entry != null ? (
                  <>
                    <span className="text-[var(--color-buy)]">+3% {fmtNum(levels.entry * 1.03)}</span>
                    <span className="text-[var(--color-buy)]">+6% {fmtNum(levels.entry * 1.06)}</span>
                    <span className="text-[var(--color-sell)]">−3% {fmtNum(levels.entry * 0.97)}</span>
                  </>
                ) : null}
              </div>
            </div>

            {/* D/E/F — độ vững tín hiệu: thanh khoản · độ bền qua phiên · đồng thuận intraday */}
            {(() => {
              const r = robMap.get(sel.symbol);
              const adtv = adtvOf(sel);
              const bd = r ? Number(r.buy_days_15d) || 0 : 0;
              const td = r ? Number(r.total_days_15d) || 0 : 0;
              const bs = r ? Number(r.buy_snaps_today) || 0 : 0;
              const ts = r ? Number(r.total_snaps_today) || 0 : 0;
              return (
                <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-[11px]">
                  <span className="font-medium">Độ vững tín hiệu:</span>
                  <span className="flex items-center gap-1.5">
                    Thanh khoản <LiqBadge adtv={adtv} />
                  </span>
                  {td ? (
                    <span title="Số phiên (ngày) mã giữ tín hiệu BUY trong ~15 phiên gần nhất.">
                      Bền qua phiên{" "}
                      <b style={{ color: robColor(bd / td) }}>{bd}/{td} phiên</b>
                    </span>
                  ) : null}
                  {ts ? (
                    <span title="Số lần chạy intraday hôm nay mã vẫn là BUY / tổng số lần chạy.">
                      Đồng thuận hôm nay{" "}
                      <b style={{ color: robColor(bs / ts) }}>{bs}/{ts} snap</b>
                      {r?.first_buy_snap_vn ? <span className="text-[var(--color-muted)]"> · từ {r.first_buy_snap_vn}</span> : null}
                    </span>
                  ) : null}
                  <span className="ml-auto italic text-[var(--color-muted)]">
                    {adtv != null && adtv < 10 ? "⚠ thanh khoản mỏng — vào/ra dễ trượt giá" : "bền + đồng thuận cao ⇒ tín hiệu đáng tin hơn"}
                  </span>
                </div>
              );
            })()}

            {/* A/B — kỳ vọng lịch sử + gợi ý thoát */}
            {exp ? (
              <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-[var(--color-border)] bg-black/[0.02] px-3 py-1.5 text-[11px] dark:bg-white/[0.03]">
                <span className="font-medium">Kỳ vọng lịch sử (BUY·{exp.confidence}, n={exp.n}):</span>
                <span>Win 5 phiên{" "}
                  <b style={{ color: (num(exp.winrate_5d) ?? 0) >= 55 ? "var(--color-buy)" : (num(exp.winrate_5d) ?? 0) < 50 ? "var(--color-sell)" : "#ca8a04" }}>
                    {num(exp.winrate_5d) ?? "—"}%
                  </b>
                </span>
                <span>TB 5 phiên <b className={signClass(num(exp.avg_ret_5d))}>{num(exp.avg_ret_5d) != null ? fmtPct(num(exp.avg_ret_5d)) : "—"}</b></span>
                <span>MFE <b className="text-[var(--color-buy)]">{num(exp.avg_mfe) != null ? fmtPct(num(exp.avg_mfe)) : "—"}</b> · MAE <b className="text-[var(--color-sell)]">{num(exp.avg_mae) != null ? fmtPct(num(exp.avg_mae)) : "—"}</b></span>
                <span className="ml-auto">Gợi ý thoát: chốt quanh <b className="text-[var(--color-buy)]">+{num(exp.avg_mfe) != null ? Math.abs(num(exp.avg_mfe)!).toFixed(1) : "3"}%</b>, cắt quanh <b className="text-[var(--color-sell)]">{num(exp.avg_mae) != null ? num(exp.avg_mae)!.toFixed(1) : "-3"}%</b></span>
              </div>
            ) : (
              <div className="mb-2 rounded-md border border-dashed border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-muted)]">
                Chưa đủ mẫu lịch sử cho {sel.decision}·{String(b.confidence ?? "")} để ước lượng kỳ vọng.
              </div>
            )}

            {loading ? (
              <div className="grid h-[280px] place-items-center text-xs text-[var(--color-muted)]">Đang tải giá…</div>
            ) : (
              <>
                <PriceChart candles={candles} levels={levels} buyMarkers={markers} />
                <div className="mt-3">
                  <div className="mb-1 text-[11px] font-medium text-[var(--color-muted)]">
                    Giá trong ngày ra tín hiệu ({sel.signal_date}) — theo từng lần chạy intraday
                  </div>
                  <IntradayStrip candle={entryCandle} />
                </div>

                {/* PHÂN TÍCH KỸ THUẬT (dễ hiểu) */}
                <p className="mt-3 border-t border-[var(--color-border)] pt-2 text-[10px] italic text-[var(--color-muted)]">
                  Đã vẽ trên chart: EMA50/EMA200, Bollinger(20,2), Entry ±3/±6%. Các chỉ báo dao động
                  (Williams %R, RSI, order flow…) không cùng thang giá nên diễn giải bằng chữ bên dưới.
                </p>
                <div className="grid gap-4 pt-2 lg:grid-cols-2">
                  <div>
                    <h3 className="mb-1.5 text-xs font-semibold">6 nhóm yếu tố</h3>
                    <div className="flex flex-col gap-1">
                      {factors.map((f) => (
                        <div key={f.label} className="flex items-center gap-2 text-[11px]">
                          <span className="w-40 shrink-0 truncate text-[var(--color-muted)]">{f.label}</span>
                          <div className="relative h-2 flex-1 rounded bg-black/5 dark:bg-white/10">
                            <div
                              className="absolute top-0 h-2 rounded"
                              style={{
                                backgroundColor: DIR_COLOR[f.dir],
                                left: f.norm >= 0 ? "50%" : `${50 + f.norm * 50}%`,
                                width: `${Math.min(50, Math.abs(f.norm) * 50)}%`,
                              }}
                            />
                            <div className="absolute left-1/2 top-0 h-2 w-px bg-[var(--color-border)]" />
                          </div>
                          <span className="tabular w-24 shrink-0 text-right" style={{ color: DIR_COLOR[f.dir] }}>
                            {DIR_LABEL[f.dir]}
                          </span>
                        </div>
                      ))}
                    </div>
                    <p className="mt-1 text-[10px] italic text-[var(--color-muted)]">Thanh phải = nghiêng mua, trái = nghiêng bán (độ dài = độ mạnh).</p>
                  </div>

                  <div>
                    <h3 className="mb-1.5 text-xs font-semibold">Tín hiệu chi tiết (diễn giải)</h3>
                    {sigs.length ? (
                      <ul className="flex flex-col gap-1">
                        {sigs.slice(0, 10).map((s) => (
                          <li key={s.name} className="flex items-start gap-2 text-[11px]">
                            <span className="tabular w-6 shrink-0 text-right font-semibold" style={{ color: DIR_COLOR[s.dir] }}>
                              {s.score > 0 ? "+" : ""}{s.score}
                            </span>
                            <span className="shrink-0 font-medium">{s.name}</span>
                            <span className="text-[var(--color-muted)]">— {s.text}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-[11px] text-[var(--color-muted)]">Không có tín hiệu nổi bật.</p>
                    )}
                    <p className="mt-1 text-[10px] italic text-[var(--color-muted)]">Diễn giải theo dấu điểm số factor — con số chính thức từ pipeline Python.</p>
                  </div>
                </div>
              </>
            )}
          </>
        ) : null}
      </div>
      </div>
    </div>
  );
}
