"use client";

import { useMemo, useState } from "react";
import {
  FACTORS,
  simulate,
  type Factor,
  type FactorNorms,
  type ScoringConfig,
} from "@/lib/scoring/simulate";
import { DecisionBadge } from "@/components/ui";

const FACTOR_LABEL: Record<Factor, string> = {
  mean_reversion: "Mean reversion",
  breakout: "Breakout",
  flow: "Flow",
  fundamental: "Fundamental",
  growth: "Growth",
  context: "Context",
};

function num(v: string): number {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

export function ConfigEditor({ initialConfig }: { initialConfig: ScoringConfig }) {
  const [cfg, setCfg] = useState<ScoringConfig>(structuredClone(initialConfig));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  // Panel mô phỏng
  const [regime, setRegime] = useState(cfg.gate_matrix.regimes[0] ?? "UPTREND");
  const [norms, setNorms] = useState<FactorNorms>({});

  const sim = useMemo(
    () => simulate(cfg, norms, regime, "trade"),
    [cfg, norms, regime],
  );

  function setWeight(lens: "trade" | "hold", f: Factor, v: number) {
    setCfg((c) => {
      const next = structuredClone(c);
      next.factor_weights[lens][f] = v;
      return next;
    });
  }
  function setGate(f: Factor, ri: number, v: number) {
    setCfg((c) => {
      const next = structuredClone(c);
      next.gate_matrix[f][ri] = v;
      return next;
    });
  }

  async function promote(force = false) {
    setBusy(true);
    setResult(null);
    try {
      const r = await fetch("/api/promote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: cfg, note, force }),
      });
      const j = await r.json();
      if (r.ok) {
        setResult("✅ Promote thành công: " + j.version_label);
      } else if (r.status === 409) {
        setResult(
          "⚠️ " + j.error + " (nhóm đổi: " + (j.changed_groups || []).join(", ") + ")",
        );
      } else {
        setResult(
          "❌ " + (j.error || "Lỗi") + (j.details ? " — " + j.details.join("; ") : ""),
        );
      }
    } catch (e) {
      setResult("❌ Lỗi mạng: " + String(e));
    } finally {
      setBusy(false);
    }
  }

  const inputCls =
    "w-full rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1 text-sm tabular";
  const regimes = cfg.gate_matrix.regimes;

  return (
    <div className="flex flex-col gap-6">
      {/* version + note */}
      <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            version_label
            <input
              className={inputCls}
              value={cfg.version_label}
              onChange={(e) => setCfg((c) => ({ ...c, version_label: e.target.value }))}
            />
          </label>
          <label className="text-sm">
            Ghi chú promote
            <input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
      </section>

      {/* Factor weights */}
      <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-3 text-sm font-semibold">Trọng số factor (weights)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--color-muted)]">
                <th className="py-1">Factor</th>
                <th className="py-1">Trade</th>
                <th className="py-1">Hold</th>
              </tr>
            </thead>
            <tbody>
              {FACTORS.map((f) => (
                <tr key={f} className="border-t border-[var(--color-border)]">
                  <td className="py-1">{FACTOR_LABEL[f]}</td>
                  {(["trade", "hold"] as const).map((lens) => (
                    <td key={lens} className="py-1 pr-3">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        max="1"
                        className={inputCls}
                        value={cfg.factor_weights[lens][f]}
                        onChange={(e) => setWeight(lens, f, num(e.target.value))}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Gate matrix */}
      <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-3 text-sm font-semibold">Gate matrix (factor × regime)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[var(--color-muted)]">
                <th className="py-1 pr-2">Factor</th>
                {regimes.map((r) => (
                  <th key={r} className="py-1 pr-2">{r}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FACTORS.map((f) => (
                <tr key={f} className="border-t border-[var(--color-border)]">
                  <td className="py-1 pr-2">{FACTOR_LABEL[f]}</td>
                  {regimes.map((_, ri) => (
                    <td key={ri} className="py-1 pr-2">
                      <input
                        type="number"
                        step="0.1"
                        min="0"
                        max="1"
                        className="w-16 rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-1 py-0.5 tabular"
                        value={cfg.gate_matrix[f][ri]}
                        onChange={(e) => setGate(f, ri, num(e.target.value))}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Simulate panel */}
      <section className="rounded-lg border border-dashed border-[var(--color-accent)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold">Mô phỏng what-if</h2>
        <p className="mb-3 text-xs text-[var(--color-muted)]">{sim.note}</p>
        <div className="grid gap-3 md:grid-cols-[1fr_auto]">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
            <label className="text-xs">
              Regime
              <select
                className={inputCls}
                value={regime}
                onChange={(e) => setRegime(e.target.value)}
              >
                {regimes.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </label>
            {FACTORS.map((f) => (
              <label key={f} className="text-xs">
                {FACTOR_LABEL[f]} norm
                <input
                  type="number"
                  step="0.1"
                  className={inputCls}
                  value={norms[f] ?? 0}
                  onChange={(e) =>
                    setNorms((n) => ({ ...n, [f]: num(e.target.value) }))
                  }
                />
              </label>
            ))}
          </div>
          <div className="flex flex-col items-center justify-center gap-2 rounded-md bg-[var(--color-bg)] p-4">
            <span className="text-xs text-[var(--color-muted)]">Ước lượng</span>
            <span className="tabular text-2xl font-bold">{sim.estScore}</span>
            <DecisionBadge decision={sim.decision} />
            <span className="text-[10px] text-[var(--color-muted)]">SIMULATION</span>
          </div>
        </div>
      </section>

      {/* Promote */}
      <section className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => promote(false)}
          disabled={busy}
          className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {busy ? "Đang promote…" : "Promote (production)"}
        </button>
        <button
          onClick={() => promote(true)}
          disabled={busy}
          className="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm text-[var(--color-muted)] disabled:opacity-60"
          title="Bỏ qua guard one-change-per-cycle (cố ý đổi >1 nhóm)"
        >
          Force (bỏ guard 1-change)
        </button>
        {result ? <span className="text-sm">{result}</span> : null}
      </section>
      <p className="text-xs text-[var(--color-muted)]">
        Promote ghi <code>active.json</code> vào repo + <code>v4_scoring_configs</code> (server-only).
        Scorer đọc active.json ở E5 (shadow-first ≥30 phiên trước khi ảnh hưởng production).
      </p>
    </div>
  );
}
