"use client";

import { Fragment, useMemo, useState } from "react";
import { DecisionBadge, InsightStrip } from "@/components/ui";
import { fmtNum, fmtPct, hmVN, signClass, fmtBil } from "@/lib/format";
import { DIR_COLOR, DIR_LABEL, factorGroupViews } from "@/lib/interpret";
import { TODAY_COMPARE_VERSIONS } from "@/lib/today-compare";

export interface TodayPriceStat {
  price: number;
  changePct: number | null;
}

export interface TodaySignal {
  symbol: string;
  scoring_version: string;
  signal_date: string;
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
  entry: string | number | null;
  stop: string | number | null;
  tp1: string | number | null;
  breakdown: Record<string, unknown> | null;
}

const QUAL_FF = 5;
const QUAL_FUND = 5;

function SignalQualityStar({ ff, fund }: { ff: number | null; fund: number | null }) {
  if (ff == null || fund == null || ff < QUAL_FF || fund < QUAL_FUND) return null;
  return (
    <span
      className="inline-flex items-center rounded border border-[var(--color-buy)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-buy)]"
      title={`Signal quality: khối ngoại mạnh (FF ${ff}≥${QUAL_FF}) và cơ bản tốt (Fund ${fund}≥${QUAL_FUND})`}
      aria-label="Signal quality"
    >
      ⭐ Quality
    </span>
  );
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}
const isBuy = (d: string | null | undefined) => {
  const decision = String(d ?? "").trim().toUpperCase().replace(/[_-]+/g, " ");
  return decision === "BUY" || decision === "STRONG BUY";
};

interface Snap {
  snap_time: string | null; decision: string | null; score: number | null;
  price: number | null; confidence: string | null;
  ffNet: number | null; ffRatio: number | null; nAlign: number | null;
  ffScore: number | null; fundScore: number | null;
  entry: number | null; stop: number | null; tp1: number | null;
  breakdown: Record<string, unknown>;
}
interface Group {
  symbol: string; snaps: Snap[]; latest: Snap;
  nSnap: number; nBuy: number; scoreFirst: number | null; scoreLast: number | null;
  priceLow: number | null; priceHigh: number | null;
}

type SortKey = "score" | "buy" | "delta" | "price_desc" | "price_asc" | "decline_1d";
type SignalMode = "both" | "strong" | "buy" | "all";

/** Match the latest decision for each version, never historical BUY snapshots. */
function matchesSignalMode(decision: string | null | undefined, mode: SignalMode): boolean {
  if (mode === "all") return true;
  const normalized = String(decision ?? "").trim().toUpperCase().replace(/[_-]+/g, " ");
  if (mode === "both") return isBuy(normalized);
  return normalized === (mode === "strong" ? "STRONG BUY" : "BUY");
}


function SnapshotFactors({ breakdown }: { breakdown: Record<string, unknown> }) {
  const groups = factorGroupViews(breakdown);
  return (
    <div className="grid gap-1.5 py-2 lg:grid-cols-2">
      {groups.map((g) => (
        <div key={g.key} className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold">{g.label}</span>
            <span className="tabular text-[10px] font-semibold" style={{ color: DIR_COLOR[g.dir] }}>
              {g.rawTotal > 0 ? "+" : ""}{g.rawTotal}<span className="font-normal text-[var(--color-muted)]">/±{g.spanTotal}</span>
            </span>
            <span className="ml-auto text-[10px] font-medium" style={{ color: DIR_COLOR[g.dir] }}>{DIR_LABEL[g.dir]}</span>
          </div>
          {g.members.length ? (
            <ul className="mt-1 space-y-1">
              {g.members.map((m) => (
                <li key={m.key} className="flex flex-wrap items-start gap-x-1.5 text-[11px] leading-tight">
                  <span className="tabular w-10 shrink-0 text-right font-semibold" style={{ color: DIR_COLOR[m.dir] }}>{m.score > 0 ? "+" : ""}{m.score}<span className="font-normal text-[var(--color-muted)]">/±{m.span}</span></span>
                  <span className="font-medium">{m.name}</span>
                  <span className="text-[var(--color-muted)]">— {m.text}</span>
                  {m.raw ? <span className="ml-auto rounded bg-black/5 px-1 text-[10px] tabular dark:bg-white/10">{m.raw}</span> : null}
                </li>
              ))}
            </ul>
          ) : <p className="mt-1 text-[10px] italic text-[var(--color-muted)]">Không có chỉ báo nổi bật ở snapshot này.</p>}
        </div>
      ))}
    </div>
  );
}
type TodayCompareVersion = (typeof TODAY_COMPARE_VERSIONS)[number];
const VERSION_LABELS: Record<TodayCompareVersion, string> = {
  "v4.17": "v4.17",
  "v4.18": "v4.18",
  "v4.19-shadow": "v4.19",
};

type VersionGroup = Group & { version: TodayCompareVersion };
type CompareRow = { symbol: string; byVersion: Partial<Record<TodayCompareVersion, VersionGroup>> };

function latestScore(group: VersionGroup | undefined): number {
  return group?.scoreLast ?? -999;
}

function cellTone(decision: string | null | undefined): string {
  if (decision === "STRONG BUY") return "border-[var(--color-strong-buy)]/50 bg-[var(--color-strong-buy)]/[0.08]";
  if (decision === "BUY") return "border-[var(--color-buy)]/40 bg-[var(--color-buy)]/[0.06]";
  if (decision === "SELL" || decision === "STRONG SELL") return "border-[var(--color-sell)]/30 bg-[var(--color-sell)]/[0.04]";
  return "border-[var(--color-border)] bg-[var(--color-bg)]";
}

export function TodayBoard({ signals, versionDates, priceStats }: { signals: TodaySignal[]; versionDates: Record<string, string>; priceStats: Record<string, TodayPriceStat> }) {
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [signalMode, setSignalMode] = useState<SignalMode>("both");
  const [hideThin, setHideThin] = useState(false);
  const [liquidityThreshold, setLiquidityThreshold] = useState("10");
  const [commonOnly, setCommonOnly] = useState(false);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [openSnap, setOpenSnap] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const groups = useMemo<VersionGroup[]>(() => {
    const by = new Map<string, Snap[]>();
    for (const signal of signals) {
      if (!TODAY_COMPARE_VERSIONS.includes(signal.scoring_version as TodayCompareVersion)) continue;
      const key = `${signal.scoring_version}:${signal.symbol}`;
      const snaps = by.get(key) ?? [];
      snaps.push({
        snap_time: signal.snap_time,
        decision: signal.decision,
        score: num(signal.score_trade),
        price: num(signal.price),
        confidence: signal.confidence,
        ffNet: num(signal.ff_intra_net),
        ffRatio: num(signal.ff_intra_ratio),
        nAlign: num(signal.n_aligned),
        ffScore: num(signal.ff_score),
        fundScore: num(signal.fundamental_score),
        entry: num(signal.entry),
        stop: num(signal.stop),
        tp1: num(signal.tp1),
        breakdown: signal.breakdown ?? {},
      });
      by.set(key, snaps);
    }

    const result: VersionGroup[] = [];
    for (const [key, snaps] of by) {
      const split = key.indexOf(":");
      const version = key.slice(0, split) as TodayCompareVersion;
      const symbol = key.slice(split + 1);
      snaps.sort((a, b) => String(a.snap_time).localeCompare(String(b.snap_time)));
      const latest = snaps[snaps.length - 1];
      const prices = snaps.map((snap) => snap.price).filter((price): price is number => price != null);
      result.push({
        version,
        symbol,
        snaps,
        latest,
        nSnap: snaps.length,
        nBuy: snaps.filter((snap) => isBuy(snap.decision)).length,
        scoreFirst: snaps[0].score,
        scoreLast: latest.score,
        priceLow: prices.length ? Math.min(...prices) : null,
        priceHigh: prices.length ? Math.max(...prices) : null,
      });
    }
    return result;
  }, [signals]);

  // Use the newest snapshot carrying a valid ADTV across all three versions.
  // At identical timestamps prefer the newer scoring version (v4.19 → v4.18 → v4.17).
  const liquidityBySymbol = useMemo(() => {
    const latest = new Map<string, { adtv: number; time: string; versionOrder: number }>();
    for (const group of groups) {
      const versionOrder = TODAY_COMPARE_VERSIONS.indexOf(group.version);
      for (const snap of group.snaps) {
        const adtv = num(snap.breakdown.adtv_bil);
        if (adtv == null || adtv < 0) continue;
        const time = snap.snap_time ?? "";
        const prior = latest.get(group.symbol);
        if (!prior || time > prior.time || (time === prior.time && versionOrder < prior.versionOrder)) {
          latest.set(group.symbol, { adtv, time, versionOrder });
        }
      }
    }
    return new Map([...latest.entries()].map(([symbol, value]) => [symbol, value.adtv]));
  }, [groups]);
  const parsedThreshold = Number(liquidityThreshold);
  const minLiquidity = liquidityThreshold.trim() !== "" && Number.isFinite(parsedThreshold) && parsedThreshold >= 0
    ? parsedThreshold : 10;

  const rows = useMemo<CompareRow[]>(() => {
    const bySymbol = new Map<string, CompareRow>();
    for (const group of groups) {
      const row = bySymbol.get(group.symbol) ?? { symbol: group.symbol, byVersion: {} };
      row.byVersion[group.version] = group;
      bySymbol.set(group.symbol, row);
    }
    const query = q.trim().toUpperCase();
    const result = [...bySymbol.values()].filter((row) => {
      if (query && !row.symbol.includes(query)) return false;
      const hasAllVersions = TODAY_COMPARE_VERSIONS.every((version) => row.byVersion[version]);
      if (commonOnly && !hasAllVersions) return false;
      if (signalMode !== "all") {
        const matches = (version: TodayCompareVersion) => matchesSignalMode(row.byVersion[version]?.latest.decision, signalMode);
        if (commonOnly ? !TODAY_COMPARE_VERSIONS.every(matches) : !TODAY_COMPARE_VERSIONS.some(matches)) return false;
      }
      const adtv = liquidityBySymbol.get(row.symbol);
      if (hideThin && adtv != null && adtv < minLiquidity) return false;
      return true;
    });
    const scoreDelta = (group: VersionGroup | undefined) => group ? (group.scoreLast ?? 0) - (group.scoreFirst ?? 0) : -999;
    const compareNumber = (a: number | null, b: number | null, ascending: boolean): number => {
      if (a == null) return b == null ? 0 : 1;
      if (b == null) return -1;
      return ascending ? a - b : b - a;
    };
    result.sort((a, b) => {
      if (sortKey === "price_desc" || sortKey === "price_asc") {
        const comparison = compareNumber(priceStats[a.symbol]?.price ?? null, priceStats[b.symbol]?.price ?? null, sortKey === "price_asc");
        return comparison || a.symbol.localeCompare(b.symbol);
      }
      if (sortKey === "decline_1d") {
        // Most negative 1D change first; missing prior-close data always sorts last.
        const comparison = compareNumber(priceStats[a.symbol]?.changePct ?? null, priceStats[b.symbol]?.changePct ?? null, true);
        return comparison || a.symbol.localeCompare(b.symbol);
      }
      if (sortKey === "buy") {
        const aBuy = TODAY_COMPARE_VERSIONS.reduce((sum, version) => sum + (a.byVersion[version]?.nBuy ?? 0), 0);
        const bBuy = TODAY_COMPARE_VERSIONS.reduce((sum, version) => sum + (b.byVersion[version]?.nBuy ?? 0), 0);
        return bBuy - aBuy || Math.max(...TODAY_COMPARE_VERSIONS.map((version) => latestScore(b.byVersion[version]))) - Math.max(...TODAY_COMPARE_VERSIONS.map((version) => latestScore(a.byVersion[version])));
      }
      if (sortKey === "delta") {
        return Math.max(...TODAY_COMPARE_VERSIONS.map((version) => scoreDelta(b.byVersion[version]))) - Math.max(...TODAY_COMPARE_VERSIONS.map((version) => scoreDelta(a.byVersion[version])));
      }
      return Math.max(...TODAY_COMPARE_VERSIONS.map((version) => latestScore(b.byVersion[version]))) - Math.max(...TODAY_COMPARE_VERSIONS.map((version) => latestScore(a.byVersion[version])));
    });
    return result;
  }, [groups, q, commonOnly, signalMode, hideThin, minLiquidity, liquidityBySymbol, priceStats, sortKey]);

  const totalSymbols = new Set(groups.map((group) => group.symbol)).size;
  const commonSymbols = useMemo(() => {
    const versionsBySymbol = new Map<string, Set<string>>();
    for (const group of groups) {
      const versions = versionsBySymbol.get(group.symbol) ?? new Set<string>();
      versions.add(group.version);
      versionsBySymbol.set(group.symbol, versions);
    }
    return [...versionsBySymbol.values()].filter((versions) => versions.size === TODAY_COMPARE_VERSIONS.length).length;
  }, [groups]);
  const sameDecision = useMemo(() => rows.filter((row) => {
    const decisions = TODAY_COMPARE_VERSIONS.map((version) => row.byVersion[version]?.latest.decision);
    return decisions.every(Boolean) && new Set(decisions).size === 1;
  }).length, [rows]);
  const versionStats = TODAY_COMPARE_VERSIONS.map((version) => {
    const versionGroups = groups.filter((group) => group.version === version);
    return {
      version,
      symbols: versionGroups.length,
      currentBuy: versionGroups.filter((group) => isBuy(group.latest.decision)).length,
      snapshots: Math.max(0, ...versionGroups.map((group) => group.nSnap)),
    };
  });

  const expanded = openKey ? (() => {
    const separator = openKey.indexOf(":");
    const symbol = openKey.slice(0, separator);
    const version = openKey.slice(separator + 1) as TodayCompareVersion;
    return rows.find((row) => row.symbol === symbol)?.byVersion[version] ?? null;
  })() : null;

  const renderVersionCell = (row: CompareRow, version: TodayCompareVersion) => {
    const group = row.byVersion[version];
    if (!group) return <div className="grid min-h-20 place-items-center rounded-md border border-dashed border-[var(--color-border)] px-2 text-xs text-[var(--color-muted)]">Chưa có dữ liệu</div>;
    const key = `${row.symbol}:${version}`;
    const delta = (group.scoreLast ?? 0) - (group.scoreFirst ?? 0);
    return (
      <button
        type="button"
        onClick={() => { setOpenKey(openKey === key ? null : key); setOpenSnap(null); }}
        aria-expanded={openKey === key}
        className={`min-h-20 w-full rounded-md border p-2 text-left transition-colors hover:border-[var(--color-accent)] ${cellTone(group.latest.decision)}`}
      >
        <div className="flex items-center gap-1.5">
          <DecisionBadge decision={group.latest.decision} />
          <SignalQualityStar ff={group.latest.ffScore} fund={group.latest.fundScore} />
          <span className="ml-auto tabular text-base font-semibold">{fmtNum(group.scoreLast)}</span>
          {group.nSnap > 1 && Math.abs(delta) >= 0.01 ? <span className={`tabular text-[10px] ${signClass(delta)}`}>{delta > 0 ? "▲" : "▼"}{Math.abs(delta).toFixed(1)}</span> : null}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-[var(--color-muted)]">
          <span className="tabular">BUY {group.nBuy}/{group.nSnap}</span>
          <span className="tabular">{hmVN(group.latest.snap_time)}</span>
          <span className="tabular">giá {fmtNum(group.latest.price)}</span>
        </div>
      </button>
    );
  };

  return (
    <div className="flex flex-col gap-2">
      <details className="card group overflow-hidden">
        <summary className="touch-target flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2 text-xs [&::-webkit-details-marker]:hidden">
          <span aria-hidden className="text-[var(--color-muted)] transition-transform group-open:rotate-90">▸</span>
          <span className="font-semibold">Thống kê so sánh 3 scoring version</span>
          <span className="text-[10px] text-[var(--color-muted)]">mặc định đóng</span>
          <span className="ml-auto text-[10px] text-[var(--color-muted)]">mở / đóng</span>
        </summary>
        <div className="border-t border-[var(--color-border)] p-2.5">
          <InsightStrip metrics={[
            ...versionStats.map((stat) => ({ value: `${stat.currentBuy}/${stat.symbols}`, label: `${VERSION_LABELS[stat.version]} BUY`, detail: `${stat.snapshots} snapshot`, tone: stat.currentBuy ? "positive" as const : "default" as const })),
            { value: commonSymbols, label: "Có ở cả 3", detail: `${totalSymbols} mã hợp nhất` },
            { value: sameDecision, label: "Đồng thuận 3 version", detail: "trên tập đang lọc" },
          ]} />
        </div>
      </details>

      <div className="card flex flex-wrap items-center gap-2 p-2">
        <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Tìm mã…" className="touch-target min-h-[32px] w-32 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-[13px] uppercase sm:max-w-[200px]" />
        <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} className="touch-target min-h-[32px] rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-xs">
          <option value="score">Score cao nhất ↓</option>
          <option value="buy">Số lần BUY ↓</option>
          <option value="delta">Score tăng mạnh ↓</option>
          <option value="price_desc">Giá cổ phiếu cao nhất ↓</option>
          <option value="price_asc">Giá cổ phiếu thấp nhất ↑</option>
          <option value="decline_1d">Giá giảm nhiều nhất 1D (%)</option>
        </select>
        <select
          aria-label="Lọc theo tín hiệu mới nhất"
          title="Lọc theo quyết định mới nhất của mỗi version"
          value={signalMode}
          onChange={(event) => setSignalMode(event.target.value as SignalMode)}
          className="touch-target min-h-[32px] rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-xs"
        >
          <option value="both">BUY + STRONG BUY</option>
          <option value="strong">Chỉ STRONG BUY</option>
          <option value="buy">Chỉ BUY</option>
          <option value="all">Tất cả tín hiệu</option>
        </select>
        <label title="Khi bật, cả ba version đều phải có tín hiệu đúng với bộ lọc đã chọn." className="flex min-h-[32px] cursor-pointer items-center gap-1.5 text-xs font-medium text-[var(--color-ink)]"><input type="checkbox" checked={commonOnly} onChange={(event) => setCommonOnly(event.target.checked)} className="h-4 w-4" />Có ở cả 3</label>
        <label className="flex min-h-[32px] cursor-pointer items-center gap-1.5 text-xs text-[var(--color-muted)]">
          <input type="checkbox" checked={hideThin} onChange={(event) => setHideThin(event.target.checked)} className="h-4 w-4" />
          Ẩn thanh khoản thấp
        </label>
        <label className="flex min-h-[32px] items-center gap-1 text-xs text-[var(--color-muted)]">
          Dưới
          <input
            aria-label="Ngưỡng thanh khoản tối thiểu (tỷ đồng mỗi phiên)"
            type="number"
            min="0"
            step="0.5"
            value={liquidityThreshold}
            onChange={(event) => setLiquidityThreshold(event.target.value)}
            className="touch-target min-h-[32px] w-[66px] rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-right text-xs tabular"
          />
          tỷ/phiên
        </label>
        <span className="ml-auto text-[11px] text-[var(--color-muted)]">{rows.length} mã</span>
      </div>

      {rows.length === 0 ? <div className="card px-3 py-8 text-center text-sm text-[var(--color-muted)]">Không có mã khớp bộ lọc hiện tại.</div> : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[860px] table-fixed text-xs">
            <thead className="sticky top-0 z-10 bg-[var(--color-surface)] text-left">
              <tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
                <th className="w-20 px-3 py-2 font-medium">Mã</th>
                {TODAY_COMPARE_VERSIONS.map((version) => <th key={version} className="px-2 py-2 font-medium"><span className="font-mono font-semibold text-[var(--color-ink)]">{VERSION_LABELS[version]}</span><span className="ml-2 text-[10px]">{versionDates[version] ?? "chưa có run"}</span></th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isExpanded = expanded?.symbol === row.symbol;
                return (
                  <Fragment key={row.symbol}>
                    <tr className="border-b border-[var(--color-border)]/70 align-top">
                      <td className="px-3 py-3">
                        <span className="sticky left-0 text-sm font-semibold">{row.symbol}</span>
                        <div title="Giá snapshot gần nhất trên 3 version; % 1D so với đóng cửa phiên giao dịch trước" className="mt-1 text-[10px] tabular text-[var(--color-muted)]">
                          <span>Giá {priceStats[row.symbol] ? fmtNum(priceStats[row.symbol].price) : "—"}</span>
                          <span className={`ml-1 ${signClass(priceStats[row.symbol]?.changePct)}`}>
                            1D {priceStats[row.symbol]?.changePct != null ? fmtPct(priceStats[row.symbol].changePct, 1) : "—"}
                          </span>
                        </div>
                        <div title="Thanh khoản giá trị trung bình mỗi phiên (ADTV) từ snapshot mới nhất có dữ liệu" className="mt-1 text-[10px] tabular text-[var(--color-muted)]">
                          ⚡ {liquidityBySymbol.get(row.symbol) == null
                            ? "Chưa có TK"
                            : liquidityBySymbol.get(row.symbol)!.toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " tỷ"}
                        </div>
                      </td>
                      {TODAY_COMPARE_VERSIONS.map((version) => <td key={version} className="px-2 py-2">{renderVersionCell(row, version)}</td>)}
                    </tr>
                    {isExpanded && expanded ? (
                      <tr className="border-b border-[var(--color-border)] bg-black/[0.015] dark:bg-white/[0.025]">
                        <td colSpan={4} className="px-3 py-3">
                          <div className="mb-2 flex flex-wrap items-center gap-2"><span className="font-semibold">{expanded.symbol} · {VERSION_LABELS[expanded.version]}</span><span className="text-[var(--color-muted)]">{expanded.nSnap} snapshot trong ngày</span><button type="button" onClick={() => setOpenKey(null)} className="ml-auto text-[11px] text-[var(--color-accent)]">Đóng</button></div>
                          <div className="overflow-x-auto">
                            <table className="w-full min-w-[720px] text-xs">
                              <thead className="text-left text-[11px] text-[var(--color-muted)]"><tr><th className="py-1">Giờ</th><th className="py-1">Quyết định</th><th className="py-1 text-right">Score</th><th className="py-1 text-right">Giá</th><th className="py-1 text-right">Entry/SL/TP</th><th className="py-1 text-right">NN lũy kế</th></tr></thead>
                              <tbody>{expanded.snaps.map((snap, index) => {
                                const snapKey = `${expanded.symbol}:${expanded.version}:${snap.snap_time ?? index}`;
                                const snapOpen = openSnap === snapKey;
                                const ffClass = snap.ffNet == null ? "text-[var(--color-muted)]" : snap.ffNet > 0 ? "text-[var(--color-buy)]" : "text-[var(--color-sell)]";
                                return <Fragment key={snapKey}><tr tabIndex={0} role="button" aria-expanded={snapOpen} onClick={() => setOpenSnap(snapOpen ? null : snapKey)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setOpenSnap(snapOpen ? null : snapKey); }} className="cursor-pointer border-t border-[var(--color-border)]/60 hover:bg-black/[0.025] dark:hover:bg-white/[0.025]"><td className="py-1.5 tabular">{snapOpen ? "▴" : "▾"} {hmVN(snap.snap_time)}</td><td className="py-1.5"><DecisionBadge decision={snap.decision} /></td><td className="py-1.5 text-right tabular">{fmtNum(snap.score)}</td><td className="py-1.5 text-right tabular">{fmtNum(snap.price)}</td><td className="py-1.5 text-right tabular">{isBuy(snap.decision) && snap.entry != null ? <span><span className="text-[var(--color-accent)]">{fmtNum(snap.entry)}</span>/<span className="text-[var(--color-sell)]">{fmtNum(snap.stop)}</span>/<span className="text-[var(--color-buy)]">{fmtNum(snap.tp1)}</span></span> : "—"}</td><td className={`py-1.5 text-right tabular ${ffClass}`}>{fmtBil(snap.ffNet)}</td></tr>{snapOpen ? <tr><td colSpan={6}><SnapshotFactors breakdown={snap.breakdown} /></td></tr> : null}</Fragment>;
                              })}</tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}