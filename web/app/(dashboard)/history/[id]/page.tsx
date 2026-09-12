import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeader, Card, DecisionBadge } from "@/components/ui";
import { createClient } from "@/lib/supabase/server";
import { fmtNum, fmtPct, signClass, snapHM } from "@/lib/format";

export const dynamic = "force-dynamic";

// Nhóm field trong breakdown để hiển thị có cấu trúc. Chỉ render key có mặt.
const FACTOR_SCORES = [
  "s_willr_mr", "s_bb_mr", "s_overext_ema", "s_rs_reversal", "s_deep_dd",
  "s_dist_52w", "s_vol_ratio_h", "s_ff_net", "s_of_phasefix", "s_prop_5d",
  "s_insider", "s_fund_core", "s_growth_core", "s_mkt_context", "s_trend_st",
  "s_depth_wall", "s_cf_core",
];
const NORMS = [
  "trade_mean_reversion_norm", "trade_breakout_norm", "trade_flow_norm",
  "trade_fundamental_norm", "trade_growth_norm", "trade_context_norm",
];
const RANKS = [
  "rank_fund_grp", "rank_fund_uni", "rank_trend_grp", "rank_ff_grp",
  "rank_cf_grp", "rank_growth_grp",
];

function KV({ obj, keys }: { obj: Record<string, unknown>; keys: string[] }) {
  const present = keys.filter((k) => obj[k] !== undefined && obj[k] !== null);
  if (!present.length) return <p className="text-xs text-[var(--color-muted)]">—</p>;
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
      {present.map((k) => (
        <div key={k} className="flex justify-between border-b border-[var(--color-border)] py-1">
          <span className="text-xs text-[var(--color-muted)]">{k}</span>
          <span className="tabular font-medium">{String(obj[k])}</span>
        </div>
      ))}
    </div>
  );
}

export default async function SignalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const numId = parseInt(id, 10);
  if (!Number.isFinite(numId)) notFound();

  const supabase = await createClient();
  const { data: sig } = await supabase
    .from("v4_signals")
    .select("*")
    .eq("id", numId)
    .maybeSingle();

  if (!sig) notFound();
  const b: Record<string, unknown> = sig.breakdown ?? {};

  // Outcome (nếu đã chín): match theo symbol + signal_date + snap_time(text từ breakdown).
  const snapText = String(b.snap_time ?? "");
  const { data: outcome } = await supabase
    .from("v4_outcomes")
    .select("ret_1d, ret_3d, ret_5d, ret_10d, mfe_pct, mae_pct, eval_date, n_bars, lens")
    .eq("symbol", sig.symbol)
    .eq("signal_date", sig.signal_date)
    .eq("snap_time", snapText)
    .maybeSingle();

  const gates = (b.gates ?? {}) as Record<string, unknown>;

  return (
    <>
      <Link href="/history" className="mb-3 inline-block text-xs text-[var(--color-accent)] hover:underline">
        ← Lịch sử
      </Link>
      <PageHeader
        title={`${sig.symbol} · ${sig.signal_date} ${snapHM(sig.snap_time)}`}
        desc={`scoring ${sig.scoring_version ?? "—"} · gate ${sig.gate_version ?? "—"} · ${b.industry ?? ""}`}
      />

      {/* Tổng quan */}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card>
          <div className="text-xs text-[var(--color-muted)]">Quyết định</div>
          <div className="mt-1"><DecisionBadge decision={sig.decision} /></div>
        </Card>
        <Card>
          <div className="text-xs text-[var(--color-muted)]">Score trade</div>
          <div className="tabular mt-1 text-lg font-semibold">{fmtNum(sig.score_trade)}</div>
        </Card>
        <Card>
          <div className="text-xs text-[var(--color-muted)]">Regime</div>
          <div className="mt-1 text-sm font-medium">{sig.regime ?? "—"}</div>
        </Card>
        <Card>
          <div className="text-xs text-[var(--color-muted)]">Confidence</div>
          <div className="mt-1 text-sm font-medium">{String(b.confidence ?? "—")}</div>
        </Card>
      </div>

      {/* Outcome */}
      {outcome ? (
        <Section title={`Kết quả forward (${outcome.lens}, eval ${outcome.eval_date})`}>
          <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-sm sm:grid-cols-6">
            {(["ret_1d", "ret_3d", "ret_5d", "ret_10d", "mfe_pct", "mae_pct"] as const).map((k) => (
              <div key={k} className="flex flex-col border-b border-[var(--color-border)] py-1">
                <span className="text-xs text-[var(--color-muted)]">{k}</span>
                <span className={`tabular font-medium ${signClass(outcome[k])}`}>{fmtPct(outcome[k])}</span>
              </div>
            ))}
          </div>
        </Section>
      ) : (
        <Section title="Kết quả forward">
          <p className="text-xs text-[var(--color-muted)]">Chưa chín (PENDING) hoặc chưa sync outcome.</p>
        </Section>
      )}

      {/* Trade levels */}
      <Section title="Mức giao dịch">
        <KV obj={b} keys={["price", "entry", "stop", "tp1", "tp2", "adtv_bil", "size_band", "exchange"]} />
      </Section>

      {/* Gates */}
      <Section title="Gate theo regime (hệ số nhân)">
        <KV obj={gates} keys={Object.keys(gates)} />
      </Section>

      {/* Factor scores */}
      <Section title="Điểm factor (s_*)">
        <KV obj={b} keys={FACTOR_SCORES} />
      </Section>

      {/* Supergroup norms */}
      <Section title="Điểm chuẩn hoá 6 nhóm (trade)">
        <KV obj={b} keys={NORMS} />
      </Section>

      {/* Ranks */}
      <Section title="Xếp hạng (rank)">
        <KV obj={b} keys={RANKS} />
      </Section>

      {/* Shadow */}
      <Section title="Shadow (đối chứng)">
        <KV
          obj={b}
          keys={[
            "score_trade_nomr", "decision_nomr", "_nomr_delta",
            "score_trade_altfund", "decision_altfund", "_altfund_delta",
            "score_trade_rank", "decision_rank", "_rank_delta",
            "score_trade_gate1", "decision_gate1", "_gate1_delta",
          ]}
        />
      </Section>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </div>
  );
}
