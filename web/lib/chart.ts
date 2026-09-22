// Dựng dữ liệu chart cho E7 từ giá snap trong v4_signals (ADR-010).
// ⚠️ Nến dựng từ giá snap (≤~7 điểm/ngày), KHÔNG phải tick OHLC đầy đủ.

import { hmVN } from "./format";

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
      snaps: day.map((d) => ({ t: hmVN(d.snap_time), price: d.price })),
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

/** MA đơn giản trên giá đóng cửa daily (từ giá snap). null cho tới khi đủ period. */
export function computeMA(candles: Candle[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < candles.length; i++) {
    if (i + 1 < period) {
      out.push(null);
      continue;
    }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += candles[j].close;
    out.push(sum / period);
  }
  return out;
}

/** EMA trên giá đóng cửa daily. Seed = SMA(period) tại điểm đủ dữ liệu; null trước đó. */
export function computeEMA(candles: Candle[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const out: (number | null)[] = [];
  let ema: number | null = null;
  for (let i = 0; i < candles.length; i++) {
    if (i + 1 < period) { out.push(null); continue; }
    if (ema === null) {
      let s = 0;
      for (let j = i - period + 1; j <= i; j++) s += candles[j].close;
      ema = s / period;
    } else {
      ema = candles[i].close * k + ema * (1 - k);
    }
    out.push(ema);
  }
  return out;
}

/** Bollinger Bands (period, mult) trên giá đóng cửa. null cho tới khi đủ period. */
export function computeBB(candles: Candle[], period = 20, mult = 2): {
  mid: number | null; upper: number | null; lower: number | null;
}[] {
  const out: { mid: number | null; upper: number | null; lower: number | null }[] = [];
  for (let i = 0; i < candles.length; i++) {
    if (i + 1 < period) { out.push({ mid: null, upper: null, lower: null }); continue; }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += candles[j].close;
    const mid = sum / period;
    let v = 0;
    for (let j = i - period + 1; j <= i; j++) v += (candles[j].close - mid) ** 2;
    const sd = Math.sqrt(v / period);
    out.push({ mid, upper: mid + mult * sd, lower: mid - mult * sd });
  }
  return out;
}

/**
 * Supertrend (ATR Wilder). Trả mỗi nến {value, dir}: dir='up' → xu hướng tăng
 * (đường nằm DƯỚI giá, xanh), 'down' → giảm (đường TRÊN giá, đỏ).
 * ⚠️ ATR tính từ high/low của nến SNAP (không phải tick thật) → xấp xỉ.
 */
export function computeSupertrend(
  candles: Candle[], period = 10, mult = 3,
): { value: number | null; dir: "up" | "down" | null }[] {
  const n = candles.length;
  const out = Array.from({ length: n }, () => ({ value: null as number | null, dir: null as "up" | "down" | null }));
  if (n < period + 1) return out;

  // True Range + ATR (Wilder smoothing).
  const tr: number[] = new Array(n).fill(0);
  tr[0] = candles[0].high - candles[0].low;
  for (let i = 1; i < n; i++) {
    const h = candles[i].high, l = candles[i].low, pc = candles[i - 1].close;
    tr[i] = Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc));
  }
  const atr: number[] = new Array(n).fill(NaN);
  let seed = 0;
  for (let i = 1; i <= period; i++) seed += tr[i];
  atr[period] = seed / period;
  for (let i = period + 1; i < n; i++) atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period;

  let prevFU = 0, prevFL = 0, prevST = 0;
  for (let i = period; i < n; i++) {
    const hl2 = (candles[i].high + candles[i].low) / 2;
    const bu = hl2 + mult * atr[i];
    const bl = hl2 - mult * atr[i];
    const pc = candles[i - 1].close;
    const fu = (bu < prevFU || pc > prevFU) ? bu : prevFU;
    const fl = (bl > prevFL || pc < prevFL) ? bl : prevFL;

    let st: number;
    if (i === period) {
      st = candles[i].close <= fu ? fu : fl; // khởi tạo
    } else if (prevST === prevFU) {
      st = candles[i].close <= fu ? fu : fl;
    } else {
      st = candles[i].close >= fl ? fl : fu;
    }
    const dir: "up" | "down" = st === fl ? "up" : "down";
    out[i] = { value: st, dir };
    prevFU = fu; prevFL = fl; prevST = st;
  }
  return out;
}

/** Nến nào chạm TP (high ≥ tp) — dùng highlight. */
export function tpHit(candles: Candle[], levels: Levels) {
  const hit1 = levels.tp1 != null && candles.some((c) => c.date >= levels.signalDate && c.high >= levels.tp1!);
  const hit2 = levels.tp2 != null && candles.some((c) => c.date >= levels.signalDate && c.high >= levels.tp2!);
  const hitStop = levels.stop != null && candles.some((c) => c.date >= levels.signalDate && c.low <= levels.stop!);
  return { hit1, hit2, hitStop };
}
