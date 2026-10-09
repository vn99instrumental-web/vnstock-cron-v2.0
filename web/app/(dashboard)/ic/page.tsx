import { PageHeader, EmptyState } from "@/components/ui";
import { createClient } from "@/lib/supabase/server";
import { FACTOR_GROUPS, signalName } from "@/lib/interpret";
import { FactorVerMatrix, type FactorVerRow } from "@/components/factor-ver-matrix";
import { FactorICTable, type MargRow } from "@/components/factor-ic-table";

export const dynamic = "force-dynamic";

/** Ã nghÄ©a tá»«ng nhÃ¢n tá»‘ (bÃ¡m Ä‘á»‹nh nghÄ©a pipeline: FACTOR_GROUPS). */
const FACTOR_INFO: Record<string, { label: string; desc: string; members: string[] }> = {
  score_trade: {
    label: "Äiá»ƒm tá»•ng (score_trade)",
    desc: "Gá»™p táº¥t cáº£ cÃ¡c nhÃ³m nhÃ¢n tá»‘ thÃ nh 1 Ä‘iá»ƒm cuá»‘i â€” cháº¥t lÆ°á»£ng cá»§a tÃ­n hiá»‡u MUA nÃ³i chung. IC hÃ ng nÃ y = Ä‘á»™ tin cáº­y cá»§a quyáº¿t Ä‘á»‹nh.",
    members: [],
  },
  ...Object.fromEntries(
    FACTOR_GROUPS.map((g) => [g.key, { label: g.label, desc: g.desc, members: g.members.map(signalName) }]),
  ),
};

/** Diá»…n giáº£i Ä‘á»™ máº¡nh + hÆ°á»›ng cá»§a má»™t Ã´ IC (dÃ¹ng cho tooltip). */
function icMeaning(ic: number | null): { strength: string; dir: string } {
  if (ic === null || !Number.isFinite(ic)) return { strength: "chÆ°a cÃ³ dá»¯ liá»‡u", dir: "" };
  const a = Math.abs(ic);
  const strength = a < 0.02 ? "gáº§n nhÆ° khÃ´ng dá»± bÃ¡o" : a < 0.05 ? "cÃ³ tÃ­n hiá»‡u" : a < 0.1 ? "tá»‘t" : "ráº¥t máº¡nh";
  const dir = ic > 0 ? "thuáº­n (Ä‘iá»ƒm cao â‡’ lá»i cao)" : ic < 0 ? "nghá»‹ch (Ä‘iá»ƒm cao â‡’ lá»—)" : "trung tÃ­nh";
  return { strength, dir };
}

// â”€â”€ IC breakdown (chá»‰ sá»‘ con / ngÃ nh) â€” Æ°á»›c lÆ°á»£ng Spearman gá»™p, tham chiáº¿u â”€â”€
interface BrkRow { key: string; horizon: number; ic: number | null; n: number }
type BrkGroup = { name: string; h: Map<number, { ic: number | null; n: number }> };

function groupBrk(rows: BrkRow[]): BrkGroup[] {
  const m = new Map<string, Map<number, { ic: number | null; n: number }>>();
  for (const r of rows) {
    if (!m.has(r.key)) m.set(r.key, new Map());
    m.get(r.key)!.set(r.horizon, { ic: r.ic, n: r.n });
  }
  const out: BrkGroup[] = [...m.entries()].map(([name, h]) => ({ name, h }));
  out.sort((a, b) => (b.h.get(5)?.ic ?? -99) - (a.h.get(5)?.ic ?? -99)); // máº¡nh nháº¥t @5d lÃªn Ä‘áº§u
  return out;
}

const HORIZONS = [1, 3, 5, 10];
const FACTOR_ORDER = [
  "score_trade", "mean_reversion", "breakout", "flow",
  "fundamental", "growth", "context",
];

interface ICRow {
  config_version: string;
  factor: string;
  horizon: number;
  ic: number | null;
  n: number | null;
}

/** MÃ u diverging: dÆ°Æ¡ng xanh lÃ¡, Ã¢m Ä‘á», Ä‘áº­m theo |IC| (chuáº©n hoÃ¡ Â±0.2). */
function icCell(ic: number | null): { bg: string; fg: string } {
  if (ic === null || !Number.isFinite(ic)) return { bg: "transparent", fg: "var(--color-muted)" };
  const a = Math.min(1, Math.abs(ic) / 0.2) * 0.8;
  const bg = ic >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`;
  return { bg, fg: a > 0.45 ? "#fff" : "var(--color-ink)" };
}

/** Báº£ng heatmap breakdown: hÃ ng = chá»‰ sá»‘/ngÃ nh (Ä‘Ã£ sort theo IC 5d), cá»™t = horizon. */
function BreakdownTable({
  groups, colLabel, nameOf, minN = 30,
}: {
  groups: BrkGroup[];
  colLabel: string;
  nameOf: (k: string) => string;
  minN?: number;
}) {
  const rows = groups.filter((g) => (g.h.get(5)?.n ?? 0) >= minN);
  if (!rows.length) return <p className="text-xs text-[var(--color-muted)]">ChÆ°a Ä‘á»§ dá»¯ liá»‡u.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full text-sm">
        <thead className="bg-black/[0.03] text-xs text-[var(--color-muted)] dark:bg-white/[0.03]">
          <tr>
            <th className="px-3 py-2 text-left">{colLabel}</th>
            {HORIZONS.map((h) => <th key={h} className="px-3 py-2 text-center">{h}d</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => (
            <tr key={g.name} className="border-t border-[var(--color-border)]">
              <td className="px-3 py-2 font-medium" title={g.name !== nameOf(g.name) ? g.name : undefined}>{nameOf(g.name)}</td>
              {HORIZONS.map((h) => {
                const c = g.h.get(h);
                const ic = c?.ic ?? null;
                const { bg, fg } = icCell(ic);
                const m = icMeaning(ic);
                const title = c
                  ? `${nameOf(g.name)} Â· sau ${h} phiÃªn\n` +
                    (ic === null ? "ChÆ°a Ä‘á»§ dá»¯ liá»‡u" : `IC ${(ic >= 0 ? "+" : "") + ic.toFixed(3)} â€” ${m.strength}, ${m.dir}`) +
                    `\nn = ${c.n} quan sÃ¡t (gá»™p má»i version)`
                  : "â€”";
                return (
                  <td key={h} className="tabular cursor-help px-3 py-2 text-center" style={{ backgroundColor: bg, color: fg }} title={title}>
                    {ic === null ? "â€”" : (ic >= 0 ? "+" : "") + ic.toFixed(3)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function ICPage() {
  const supabase = await createClient();
  const { data } = await supabase
    .from("v4_ic_metrics")
    .select("config_version, factor, horizon, ic, n")
    .order("config_version", { ascending: false })
    .order("factor", { ascending: true })
    .order("horizon", { ascending: true });

  const rows = (data ?? []) as ICRow[];

  // Version production HIá»†N Táº I (Ä‘á»c Ä‘á»™ng tá»« run má»›i nháº¥t â€” version-agnostic).
  const { data: curRun } = await supabase
    .from("v4_runs")
    .select("scoring_version")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  const curVer = (curRun?.scoring_version as string | undefined) ?? null;
  const curHasIC = !!curVer && rows.some((r) => r.config_version === curVer);

  // IC breakdown (Æ°á»›c lÆ°á»£ng Spearman gá»™p) â€” chá»‰ sá»‘ con, ngÃ nh (gá»™p & theo version).
  const [indRes, indusVerRes, factorVerRes, margRes] = await Promise.all([
    supabase.from("v4_ic_by_indicator").select("indicator, horizon, ic, n"),
    supabase.from("v4_ic_by_industry_ver").select("version, industry, horizon, ic, n"),
    supabase.from("v4_ic_by_factor_ver").select("version, factor, horizon, ic, n"),
    supabase.from("v4_marginal_ic").select("version, indicator, factor, horizon, coef, tstat, univar_ic, n"),
  ]);
  const factorVerRows = (factorVerRes.data ?? []) as FactorVerRow[];
  const marginalRows = (margRes.data ?? []) as (MargRow & { version: string })[];
  const toBrk = (arr: Record<string, unknown>[], keyField: string): BrkRow[] =>
    arr.map((r) => ({
      key: String(r[keyField]),
      horizon: Number(r.horizon),
      ic: r.ic == null ? null : Number(r.ic),
      n: Number(r.n),
    }));
  const indGroups = groupBrk(toBrk((indRes.data ?? []) as Record<string, unknown>[], "indicator"));

  // Chá»‰ sá»‘ con GOM THEO FACTOR (mean_reversion gá»“m indicator nÃ oâ€¦).
  const indByName = new Map(indGroups.map((g) => [g.name, g]));
  const indByFactor = FACTOR_GROUPS.map((fg) => ({
    key: fg.key,
    label: fg.label,
    members: fg.members.map((m) => indByName.get(m)).filter((g): g is BrkGroup => !!g),
  })).filter((f) => f.members.length);

  // IC theo ngÃ nh TÃCH THEO VERSION (chá»‰ version cÃ³ â‰¥3 ngÃ nh Ä‘á»§ n).
  const verMap = new Map<string, BrkRow[]>();
  for (const r of (indusVerRes.data ?? []) as Record<string, unknown>[]) {
    const v = String(r.version);
    if (!verMap.has(v)) verMap.set(v, []);
    verMap.get(v)!.push({ key: String(r.industry), horizon: Number(r.horizon), ic: r.ic == null ? null : Number(r.ic), n: Number(r.n) });
  }
  const indusByVer = [...verMap.entries()]
    .map(([version, rws]) => ({ version, groups: groupBrk(rws) }))
    .filter((x) => x.groups.filter((g) => (g.h.get(5)?.n ?? 0) >= 30).length >= 3)
    .sort((a, b) => (b.version === curVer ? 1 : 0) - (a.version === curVer ? 1 : 0) || b.version.localeCompare(a.version, undefined, { numeric: true }));

  if (!rows.length) {
    return (
      <>
        <PageHeader title="Cháº¥t lÆ°á»£ng nhÃ¢n tá»‘ (IC)" desc="Forward rank-IC theo factor Ã— horizon." />
        <EmptyState
          title="ChÆ°a cÃ³ dá»¯ liá»‡u IC"
          hint="Cháº¡y scripts/export_ic_to_supabase.py (evaluator Python, E6) sau khi cÃ³ outcomes. Báº£ng v4_ic_metrics hiá»‡n rá»—ng."
        />
      </>
    );
  }

  // Danh sÃ¡ch version Ä‘á»ƒ render báº£ng há»£p nháº¥t: cÃ³ IC official HOáº¶C cÃ³ marginal.
  // Sort: version hiá»‡n táº¡i lÃªn Ä‘áº§u, rá»“i giáº£m dáº§n theo sá»‘.
  const verList = [...new Set([
    ...rows.map((r) => r.config_version),
    ...marginalRows.map((r) => r.version),
  ])].sort(
    (a, b) => (b === curVer ? 1 : 0) - (a === curVer ? 1 : 0) || b.localeCompare(a, undefined, { numeric: true }),
  );

  const sampleByVersion = verList.map((version) => {
    const byHorizon = new Map<number, number>();
    for (const r of rows) if (r.config_version === version && r.n != null) byHorizon.set(r.horizon, Math.max(byHorizon.get(r.horizon) ?? 0, Number(r.n)));
    return { version, byHorizon };
  });

  return (
    <>
      <PageHeader
        title="Cháº¥t lÆ°á»£ng nhÃ¢n tá»‘ (IC)"
        desc="Forward rank-IC (Spearman theo ngÃ y â†’ trung bÃ¬nh). TÃ­nh báº±ng Python â€” nguá»“n chÃ¢n lÃ½. Xanh = dá»± bÃ¡o thuáº­n, Ä‘á» = nghá»‹ch."
      />

      {curVer ? (
        <div className="card mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 p-2.5 text-[13px]">
          <span className="rounded-md bg-[var(--color-accent)] px-2 py-0.5 text-[11px] font-semibold text-white">HIá»†N Táº I</span>
          <span className="font-mono font-semibold">scoring {curVer}</span>
          {curHasIC ? (
            <span className="text-[var(--color-muted)]">â€” IC bÃªn dÆ°á»›i (Ä‘Ã¡nh dáº¥u &ldquo;hiá»‡n táº¡i&rdquo;).</span>
          ) : (
            <span className="text-[var(--color-muted)]">
              â€” <b className="text-[var(--color-ink)]">chÆ°a Ä‘á»§ dá»¯ liá»‡u forward Ä‘á»ƒ tÃ­nh IC</b>. Má»—i láº§n Ä‘á»•i version lÃ  reset
              forward-validation â†’ cáº§n tÃ­ch luá»¹ outcomes vÃ i phiÃªn rá»“i evaluator (Python) má»›i ghi IC. Báº£ng dÆ°á»›i lÃ  cÃ¡c
              version cÅ© Ä‘Ã£ Ä‘á»§ máº«u, dÃ¹ng Ä‘á»ƒ tham chiáº¿u.
            </span>
          )}
        </div>
      ) : null}

      <details className="card mb-6 p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold">Số lượng dữ liệu theo scoring version</summary>
        <p className="mb-2 text-[11px] text-[var(--color-muted)]">n = sá»‘ quan sÃ¡t forward Ä‘Ã£ Ä‘á»§ dá»¯ liá»‡u cho tá»«ng horizon; cÃ¡c horizon cÃ³ thá»ƒ cÃ³ sá»‘ máº«u khÃ¡c nhau.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[var(--color-muted)]"><tr className="border-b border-[var(--color-border)]"><th className="px-2 py-1.5 text-left">Version</th>{HORIZONS.map((h) => <th key={h} className="px-2 py-1.5 text-right">{h} phiÃªn</th>)}</tr></thead>
            <tbody>{sampleByVersion.map(({ version, byHorizon }) => <tr key={version} className="border-b border-[var(--color-border)] last:border-0"><td className="px-2 py-1.5 font-mono">{version}{version === curVer ? " (hiá»‡n táº¡i)" : ""}</td>{HORIZONS.map((h) => <td key={h} className="px-2 py-1.5 text-right tabular">{byHorizon.get(h)?.toLocaleString() ?? "â€”"}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </details>
      {verList.map((version) => (
        <FactorICTable
          key={version}
          version={version}
          curVer={curVer}
          official={rows.filter((r) => r.config_version === version)}
          marginal={marginalRows.filter((r) => r.version === version)}
        />
      ))}
      <details className="card mb-4 p-3 text-[13px]">
        <summary className="cursor-pointer select-none text-sm font-semibold">â„¹ï¸ IC lÃ  gÃ¬ &amp; Ä‘á»c báº£ng tháº¿ nÃ o?</summary>
        <div className="mt-2 flex flex-col gap-2 leading-relaxed text-[var(--color-muted)]">
          <p>
            <b className="text-[var(--color-ink)]">IC (Information Coefficient)</b> = tÆ°Æ¡ng quan háº¡ng (Spearman) giá»¯a
            Ä‘iá»ƒm nhÃ¢n tá»‘ lÃºc ra tÃ­n hiá»‡u vÃ  <b className="text-[var(--color-ink)]">lá»£i nhuáº­n thá»±c táº¿ sau N phiÃªn</b>.
            NÃ³i cÃ¡ch khÃ¡c: Ä‘iá»ƒm cao cÃ³ <i>tháº­t sá»±</i> Ä‘i kÃ¨m lá»i cao hÆ¡n khÃ´ng.
          </p>

          <div>
            <div className="mb-1 font-medium text-[var(--color-ink)]">Äá»c Ä‘á»™ máº¡nh |IC| (Ä‘á»‹nh lÆ°á»£ng):</div>
            <ul className="grid gap-x-4 gap-y-0.5 sm:grid-cols-2">
              <li>â‰ˆ 0 â†’ gáº§n nhÆ° khÃ´ng dá»± bÃ¡o</li>
              <li>0.02 â€“ 0.05 â†’ cÃ³ tÃ­n hiá»‡u (Ä‘Ã£ Ä‘Ã¡ng dÃ¹ng)</li>
              <li>0.05 â€“ 0.10 â†’ tá»‘t</li>
              <li>&gt; 0.10 â†’ ráº¥t máº¡nh (hiáº¿m â€” soi ká»¹ cá»¡ máº«u n káº»o overfit)</li>
            </ul>
          </div>

          <p>
            <b className="text-[var(--color-ink)]">Dáº¥u &amp; mÃ u:</b>{" "}
            <span className="font-semibold text-[var(--color-buy)]">+ xanh</span> = nhÃ¢n tá»‘ cao â‡’ lá»i cao (dá»± bÃ¡o
            thuáº­n, Ä‘Ãºng ká»³ vá»ng);{" "}
            <span className="font-semibold text-[var(--color-sell)]">âˆ’ Ä‘á»</span> = nhÃ¢n tá»‘ cao â‡’ lá»— (nghá»‹ch â€” factor
            Ä‘ang pháº£n tÃ¡c dá»¥ng, nÃªn cÃ¢n nháº¯c giáº£m/Ä‘áº£o trá»ng sá»‘). MÃ u cÃ ng Ä‘áº­m â‡’ |IC| cÃ ng lá»›n (chuáº©n hoÃ¡ Â±0.20).
          </p>

          <p>
            <b className="text-[var(--color-ink)]">Cá»™t 1d/3d/5d/10d:</b> Ä‘o vá»›i lá»£i nhuáº­n sau 1/3/5/10 phiÃªn â€” má»™t
            nhÃ¢n tá»‘ cÃ³ thá»ƒ máº¡nh á»Ÿ khung nÃ y nhÆ°ng yáº¿u á»Ÿ khung khÃ¡c. So ngang Ä‘á»ƒ biáº¿t factor dá»± bÃ¡o ngáº¯n hay dÃ i háº¡n.
          </p>

          <p>
            <b className="text-[var(--color-ink)]">HÃ ng:</b> <code>score_trade</code> = Ä‘iá»ƒm tá»•ng (cháº¥t lÆ°á»£ng tÃ­n hiá»‡u
            chung); cÃ¡c hÃ ng cÃ²n láº¡i = tá»«ng nhÃ³m nhÃ¢n tá»‘.
          </p>

          <p>
            <b className="text-[var(--color-ink)]">n (rÃª chuá»™t lÃªn Ã´) = cá»¡ máº«u.</b> n nhá» â†’ IC nhiá»…u, chÆ°a tin Ä‘Æ°á»£c.
            Æ¯u tiÃªn Ã´ cÃ³ n lá»›n vÃ  qua nhiá»u phiÃªn.
          </p>

          <p>
            <b className="text-[var(--color-ink)]">NhÃ³m theo version:</b> má»—i láº§n Ä‘á»•i SCORING_VERSION lÃ  reset
            forward-validation â†’ IC tÃ­nh riÃªng tá»«ng version. So version má»›i vá»›i cÅ© Ä‘á»ƒ biáº¿t thay Ä‘á»•i cÃ³ cáº£i thiá»‡n khÃ´ng.
          </p>

          <p className="italic">
            LÆ°u Ã½: Ä‘Ã¢y lÃ  <b>forward IC</b> (Ä‘o trÃªn tÆ°Æ¡ng lai tháº­t, khÃ´ng pháº£i backtest) â€” Ä‘Ã¡ng tin hÆ¡n, nhÆ°ng váº«n cáº§n
            Ä‘á»§ máº«u &amp; nhiá»u phiÃªn má»›i káº¿t luáº­n. Con sá»‘ chÃ­nh thá»©c do evaluator Python tÃ­nh.
          </p>
        </div>
      </details>
      <details className="card mb-6 p-3 text-[13px]">
        <summary className="cursor-pointer select-none text-sm font-semibold">ðŸ“– Ã nghÄ©a tá»«ng nhÃ¢n tá»‘ (rÃª chuá»™t lÃªn tÃªn hÃ ng / tá»«ng Ã´ Ä‘á»ƒ xem nhanh)</summary>
        <div className="mt-2 flex flex-col gap-2.5">
          {FACTOR_ORDER.filter((k) => FACTOR_INFO[k]).map((k) => {
            const info = FACTOR_INFO[k];
            return (
              <div key={k} className="border-l-2 border-[var(--color-border)] pl-2.5">
                <div className="font-mono text-[12px] font-semibold">{k}</div>
                <div className="text-[13px] font-medium">{info.label}</div>
                <div className="text-[12px] text-[var(--color-muted)]">{info.desc}</div>
                {info.members.length ? (
                  <div className="mt-0.5 text-[11px] text-[var(--color-muted)]">
                    <span className="font-medium">Chá»‰ bÃ¡o thÃ nh viÃªn:</span> {info.members.join(" Â· ")}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </details>
      <p className="mb-2 text-[12px] text-[var(--color-muted)]">
        Má»—i version: hÃ ng <b>nhÃ¢n tá»‘</b> = IC chÃ­nh thá»©c (evaluator Python, chuáº©n theo-ngÃ y) Ã— 1/3/5/10 phiÃªn. Báº¥m nhÃ¢n
        tá»‘ cÃ³ dáº¥u â–¸ Ä‘á»ƒ <b>bung ra chá»‰ bÃ¡o con</b> kÃ¨m <b>Ä‘Ã³ng gÃ³p biÃªn</b> (há»“i quy Ä‘a biáº¿n, khá»­ trÃ¹ng láº·p) + cá»™t
        <b> Káº¿t luáº­n</b> (GIá»®/tÄƒng Â· GIáº¢M/Ä‘áº£o Â· trÃ¹ng láº·p) â€” dÃ¹ng Ä‘á»ƒ combine version má»›i. RÃª chuá»™t Ã´ Ä‘á»ƒ xem n / t-stat.
      </p>
      <p className="mb-6 text-xs text-[var(--color-muted)]">
        Ã” nhÃ¢n tá»‘: Ä‘á»™ Ä‘áº­m theo |IC| (Â±0.20). Ã” chá»‰ bÃ¡o (bung): Ä‘á»™ Ä‘áº­m theo |há»‡ sá»‘ biÃªn| (Â±0.30), <b>in Ä‘áº­m = |t|â‰¥2</b>
        (cÃ³ Ã½ nghÄ©a). IC official chá»‰ cÃ³ á»Ÿ version tÃ­ch Ä‘á»§ â‰¥3 phiÃªn chÃ­n; Ä‘Ã³ng gÃ³p biÃªn cÃ³ á»Ÿ version Ä‘á»§ máº«u há»“i quy (nâ‰¥150).
      </p>

      {/* â”€â”€ Ma tráº­n IC nhÃ¢n tá»‘ Ã— Má»ŒI version (Æ°á»›c lÆ°á»£ng) â€” cÃ´ng cá»¥ combine â”€â”€ */}
      <section className="mb-6">
        <h2 className="mb-1 text-sm font-semibold">ðŸ§® So sÃ¡nh nhÃ¢n tá»‘ qua táº¥t cáº£ version â€” chá»n yáº¿u tá»‘ Ä‘á»ƒ combine</h2>
        <section className="card mb-6 p-3">
        <h2 className="mb-1 text-sm font-semibold">Sá»‘ lÆ°á»£ng dá»¯ liá»‡u theo scoring version</h2>
        <p className="mb-2 text-[11px] text-[var(--color-muted)]">n = sá»‘ quan sÃ¡t forward Ä‘Ã£ Ä‘á»§ dá»¯ liá»‡u cho tá»«ng horizon; cÃ¡c horizon cÃ³ thá»ƒ cÃ³ sá»‘ máº«u khÃ¡c nhau.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[var(--color-muted)]"><tr className="border-b border-[var(--color-border)]"><th className="px-2 py-1.5 text-left">Version</th>{HORIZONS.map((h) => <th key={h} className="px-2 py-1.5 text-right">{h} phiÃªn</th>)}</tr></thead>
            <tbody>{sampleByVersion.map(({ version, byHorizon }) => <tr key={version} className="border-b border-[var(--color-border)] last:border-0"><td className="px-2 py-1.5 font-mono">{version}{version === curVer ? " (hiá»‡n táº¡i)" : ""}</td>{HORIZONS.map((h) => <td key={h} className="px-2 py-1.5 text-right tabular">{byHorizon.get(h)?.toLocaleString() ?? "â€”"}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </section>

      <p className="mb-2 text-[12px] text-[var(--color-muted)]">
          HÃ ng = version, cá»™t = nhÃ¢n tá»‘. TÃ¬m nhÃ¢n tá»‘ <b>dÆ°Æ¡ng á»•n Ä‘á»‹nh qua nhiá»u version</b> (xanh nhiá»u cá»™t) Ä‘á»ƒ tÄƒng
          trá»ng sá»‘; nhÃ¢n tá»‘ <b>Ä‘á» dai dáº³ng</b> Ä‘á»ƒ giáº£m/Ä‘áº£o. Phá»§ háº¿t má»i version (ká»ƒ cáº£ version cÅ© n nhá») â€”
          <b> Æ°á»›c lÆ°á»£ng pooled</b>, tham chiáº¿u; con sá»‘ chuáº©n xem báº£ng official phÃ­a trÃªn.
        </p>
        <FactorVerMatrix rows={factorVerRows} curVer={curVer} minN={30} />
      </section>

      {/* â”€â”€ IC theo CHá»ˆ Sá» CON â€” gom theo nhÃ³m nhÃ¢n tá»‘ â”€â”€ */}
      <section className="mb-6">
        <h2 className="mb-1 text-sm font-semibold">ðŸ”¬ IC theo chá»‰ sá»‘ con â€” gom theo nhÃ³m nhÃ¢n tá»‘</h2>
        <section className="card mb-6 p-3">
        <h2 className="mb-1 text-sm font-semibold">Sá»‘ lÆ°á»£ng dá»¯ liá»‡u theo scoring version</h2>
        <p className="mb-2 text-[11px] text-[var(--color-muted)]">n = sá»‘ quan sÃ¡t forward Ä‘Ã£ Ä‘á»§ dá»¯ liá»‡u cho tá»«ng horizon; cÃ¡c horizon cÃ³ thá»ƒ cÃ³ sá»‘ máº«u khÃ¡c nhau.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[var(--color-muted)]"><tr className="border-b border-[var(--color-border)]"><th className="px-2 py-1.5 text-left">Version</th>{HORIZONS.map((h) => <th key={h} className="px-2 py-1.5 text-right">{h} phiÃªn</th>)}</tr></thead>
            <tbody>{sampleByVersion.map(({ version, byHorizon }) => <tr key={version} className="border-b border-[var(--color-border)] last:border-0"><td className="px-2 py-1.5 font-mono">{version}{version === curVer ? " (hiá»‡n táº¡i)" : ""}</td>{HORIZONS.map((h) => <td key={h} className="px-2 py-1.5 text-right tabular">{byHorizon.get(h)?.toLocaleString() ?? "â€”"}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </section>

      <p className="mb-2 text-[12px] text-[var(--color-muted)]">
          Má»—i nhÃ³m nhÃ¢n tá»‘ (mean_reversion, breakoutâ€¦) gá»“m cÃ¡c <b>chá»‰ bÃ¡o thÃ nh viÃªn</b> bÃªn dÆ°á»›i. IC = chá»‰ bÃ¡o nÃ o
          <b> dá»± bÃ¡o tá»‘t</b> (xanh) / <b>ngÆ°á»£c</b> (Ä‘á»). Æ¯á»›c lÆ°á»£ng Spearman rank-IC gá»™p toÃ n ká»³ (má»i version) â€” tham
          chiáº¿u, khÃ´ng pháº£i IC chÃ­nh thá»©c evaluator. RÃª chuá»™t xem n.
        </p>
        <div className="flex flex-col gap-3">
          {indByFactor.map((f) => (
            <div key={f.key}>
              <div className="mb-1 text-[13px] font-semibold">
                {f.label} <span className="font-mono text-[11px] font-normal text-[var(--color-muted)]">{f.key}</span>
              </div>
              <BreakdownTable groups={f.members} colLabel="Chá»‰ bÃ¡o" nameOf={(k) => signalName(k)} minN={100} />
            </div>
          ))}
        </div>
      </section>


      {/* â”€â”€ IC theo NGÃ€NH (gá»™p + per-version) â”€â”€ */}
      <section className="mb-4">
        <h2 className="mb-1 text-sm font-semibold">ðŸ­ IC theo ngÃ nh â€” Ä‘iá»ƒm sá»‘ hiá»‡u quáº£ á»Ÿ ngÃ nh nÃ o?</h2>
        <section className="card mb-6 p-3">
        <h2 className="mb-1 text-sm font-semibold">Sá»‘ lÆ°á»£ng dá»¯ liá»‡u theo scoring version</h2>
        <p className="mb-2 text-[11px] text-[var(--color-muted)]">n = sá»‘ quan sÃ¡t forward Ä‘Ã£ Ä‘á»§ dá»¯ liá»‡u cho tá»«ng horizon; cÃ¡c horizon cÃ³ thá»ƒ cÃ³ sá»‘ máº«u khÃ¡c nhau.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[var(--color-muted)]"><tr className="border-b border-[var(--color-border)]"><th className="px-2 py-1.5 text-left">Version</th>{HORIZONS.map((h) => <th key={h} className="px-2 py-1.5 text-right">{h} phiÃªn</th>)}</tr></thead>
            <tbody>{sampleByVersion.map(({ version, byHorizon }) => <tr key={version} className="border-b border-[var(--color-border)] last:border-0"><td className="px-2 py-1.5 font-mono">{version}{version === curVer ? " (hiá»‡n táº¡i)" : ""}</td>{HORIZONS.map((h) => <td key={h} className="px-2 py-1.5 text-right tabular">{byHorizon.get(h)?.toLocaleString() ?? "â€”"}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </section>

      <p className="mb-2 text-[12px] text-[var(--color-muted)]">
          Spearman rank-IC gá»™p giá»¯a <code>score_trade</code> vÃ  lá»£i nhuáº­n sau N phiÃªn, tÃ¡ch theo ngÃ nh, <b>riÃªng tá»«ng
          version</b> (Ä‘iá»ƒm mÃ´ hÃ¬nh Ä‘Ã¡ng tin á»Ÿ ngÃ nh nÃ o â€” xanh, ngÆ°á»£c á»Ÿ ngÃ nh nÃ o â€” Ä‘á»). Æ¯á»›c lÆ°á»£ng tham chiáº¿u.
        </p>

        {indusByVer.length ? (
          <div>
            {indusByVer.map((v) => (
              <details key={v.version} className="mb-1.5 rounded-md border border-[var(--color-border)] p-2" open={v.version === curVer}>
                <summary className="cursor-pointer select-none font-mono text-[13px] font-semibold">
                  scoring {v.version}{v.version === curVer ? " (hiá»‡n táº¡i)" : ""}
                </summary>
                <div className="mt-1.5">
                  <BreakdownTable groups={v.groups} colLabel="NgÃ nh" nameOf={(k) => k} minN={30} />
                </div>
              </details>
            ))}
          </div>
        ) : null}
      </section>
    </>
  );
}
