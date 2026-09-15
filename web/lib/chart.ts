// Dựng dữ liệu chart cho E7 từ giá snap trong v4_signals (ADR-010).
// ⚠️ Nến dựng từ giá snap (≤~7 điểm/ngày), KHÔNG phải tick OHLC đầy đủ.

export interface PricePoint {
  signal_date: string;
  snap_time: string; // "HH:MM" hoặc timestamptz
  price: number;
}

export interface Candle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  snaps: { t: string; price: number }[]; // điểm intraday trong ngày
}

function hm(ts: string): string {
  const m = String(ts).match(/T(\d{2}:\d{2})/);
  if (m) return m[1];
  const m2 = String(ts).match(/^(\d{2}:\d{2})/);
  return m2 ? m2[1] : String(ts);
}

/** Gom PricePoint theo ngày → nến daily (O=snap đầu, C=snap cuối, H=max, L=min). */
export function buildCandles(points: PricePoint[]): Candle[] {
  const byDay = new Map<string, PricePoint[]>();
  for (const p of points) {
    if (p.price == null || !Number.isFinite(p.price)) continue;
    const arr = byDay.get(p.signal_date) ?? [];
    arr.push(p);
    byDay.set(p.signal_date, arr);
  }
  const candles: Candle[] = [];
  for (const date of [...byDay.keys()].sort()) {
    const day = byDay.get(date)!.slice().sort((a, b) => a.snap_time.localeCompare(b.snap_time));
    const prices = day.map((d) => d.price);
    candles.push({
      date,
      open: prices[0],
      close: prices[prices.length - 1],
      high: Math.max(...prices),
      low: Math.min(...prices),
      snaps: day.map((d) => ({ t: hm(d.snap_time), price: d.price })),
    });
  }
  return candles;
}

export interface Levels {
  entry: number | null;
  stop: number | null;
  tp1: number | null;
  tp2: number | null;
  signalDate: string;
}

/** Nến nào chạm TP (high ≥ tp) — dùng highlight. */
export function tpHit(candles: Candle[], levels: Levels) {
  const hit1 = levels.tp1 != null && candles.some((c) => c.date >= levels.signalDate && c.high >= levels.tp1!);
  const hit2 = levels.tp2 != null && candles.some((c) => c.date >= levels.signalDate && c.high >= levels.tp2!);
  const hitStop = levels.stop != null && candles.some((c) => c.date >= levels.signalDate && c.low <= levels.stop!);
  return { hit1, hit2, hitStop };
}
