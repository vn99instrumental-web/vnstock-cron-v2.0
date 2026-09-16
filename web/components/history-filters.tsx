"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

const DECISIONS = ["", "STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"];

export function HistoryFilters() {
  const router = useRouter();
  const params = useSearchParams();
  const [date, setDate] = useState(params.get("date") ?? "");
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "");
  const [decision, setDecision] = useState(params.get("decision") ?? "");

  function apply(e: React.FormEvent) {
    e.preventDefault();
    const q = new URLSearchParams();
    if (date) q.set("date", date);
    if (symbol) q.set("symbol", symbol.toUpperCase().trim());
    if (decision) q.set("decision", decision);
    router.push("/history?" + q.toString());
  }

  const inputCls =
    "mt-1 min-h-[40px] rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-2 text-sm";

  return (
    <form onSubmit={apply} className="mb-4 flex flex-wrap items-end gap-2">
      <label className="text-xs">
        Ngày
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${inputCls} block`} />
      </label>
      <label className="text-xs">
        Mã
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="VD: ACB"
          className={`${inputCls} block w-24`}
        />
      </label>
      <label className="text-xs">
        Quyết định
        <select value={decision} onChange={(e) => setDecision(e.target.value)} className={`${inputCls} block`}>
          {DECISIONS.map((d) => (
            <option key={d} value={d}>{d || "Tất cả"}</option>
          ))}
        </select>
      </label>
      <button type="submit" className="min-h-[40px] rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white active:opacity-80">
        Lọc
      </button>
      <button
        type="button"
        onClick={() => router.push("/history")}
        className="min-h-[40px] rounded-md border border-[var(--color-border)] px-4 py-2 text-sm text-[var(--color-muted)] active:bg-black/5 dark:active:bg-white/5"
      >
        Xóa lọc
      </button>
    </form>
  );
}
