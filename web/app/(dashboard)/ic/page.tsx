import { PageHeader, EmptyState } from "@/components/ui";
import { createCachedPublicClient } from "@/lib/supabase/cached-public";
import { FACTOR_GROUPS, signalName } from "@/lib/interpret";
import { FactorVerMatrix, type FactorVerRow } from "@/components/factor-ver-matrix";
import { FactorICTable, type MargRow } from "@/components/factor-ic-table";
import { DEFAULT_SCORING_VERSION, REVIEW_VERSIONS } from "@/lib/scoring-versions";

export const dynamic = "force-dynamic";

/** Ã nghÄ©a tá»«ng nhÃ¢n tá»‘ (bÃ¡m Ä‘á»‹nh nghÄ©a pipeline: FACTOR_GROUPS). */
const FACTOR_INFO: Record<string, { label: string; desc: string; members: string[] }> = {
  score_trade: {
    label: "Äiá»ƒm tá»•ng (score_trade)",
    desc: "Gá»™p táº¥t cáº£ cÃ¡c nhÃ³m nhÃ¢n tá»‘ thÃ nh má»™t Ä‘iá»ƒm cuá»‘i â€” cháº¥t lÆ°á»£ng cá»§a tÃ­n hiá»‡u MUA nÃ³i chung. IC hÃ ng nÃ y thá»ƒ hiá»‡n Ä‘á»™ tin cáº­y cá»§a quyáº¿t Ä‘á»‹nh.",
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
  const dir = ic > 0 ? "thuáº­n (Äiá»ƒm cao â‡’ lá»i cao)" : ic < 0 ? "nghá»‹ch (Äiá»ƒm cao â‡’ lá»—)" : "trung tÃ­nh";
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

const HORIZONS = [3, 5, 10];
const FACTOR_ORDER = [
  "score_trade", "mean_reversion", "breakout", "flow",
  "fundamental", "growth", "context",
];
const TECHNICAL_TERMS = [
  { term: "Spearman (Ï)", meaning: "Äo má»©c Ä‘á»™ hai biáº¿n tÄƒng hoáº·c giáº£m cÃ¹ng thá»© tá»±, khÃ´ng yÃªu cáº§u quan há»‡ tuyáº¿n tÃ­nh.", formula: "Ï = 1 âˆ’ 6Î£dÂ² / [n(nÂ²âˆ’1)] (khi khÃ´ng cÃ³ háº¡ng trÃ¹ng)", reading: "+1: cÃ¹ng chiá»u hoÃ n toÃ n; 0: khÃ´ng cÃ³ quan há»‡ háº¡ng; âˆ’1: ngÆ°á»£c chiá»u hoÃ n toÃ n." },
  { term: "IC (Information Coefficient)", meaning: "Spearman giá»¯a Ä‘iá»ƒm tÃ­n hiá»‡u hÃ´m nay vÃ  lá»£i nhuáº­n tÆ°Æ¡ng lai; Ä‘o kháº£ nÄƒng xáº¿p háº¡ng cá»• phiáº¿u.", formula: "IC = Spearman(score, future return)", reading: "|IC| < 0,02: yáº¿u; 0,02â€“0,05: cÃ³ tÃ­n hiá»‡u; 0,05â€“0,10: tá»‘t; > 0,10: máº¡nh. IC Ã¢m lÃ  dá»± bÃ¡o ngÆ°á»£c." },
  { term: "Williams %R", meaning: "Cho biáº¿t giÃ¡ Ä‘Ã³ng cá»­a Ä‘ang náº±m gáº§n Ä‘á»‰nh hay Ä‘Ã¡y cá»§a biÃªn giÃ¡ N phiÃªn.", formula: "%R = âˆ’100 Ã— (HighN âˆ’ Close) / (HighN âˆ’ LowN)", reading: "Tá»« âˆ’100 Ä‘áº¿n 0. DÆ°á»›i âˆ’80: quÃ¡ bÃ¡n; trÃªn âˆ’20: quÃ¡ mua. KhÃ´ng nÃªn dÃ¹ng riÃªng láº» lÃ m lá»‡nh mua/bÃ¡n." },
  { term: "Bollinger Bands / %B", meaning: "Äo vá»‹ trÃ­ giÃ¡ so vá»›i dáº£i biáº¿n Ä‘á»™ng quanh trung bÃ¬nh Ä‘á»™ng.", formula: "%B = (Price âˆ’ Lower Band) / (Upper Band âˆ’ Lower Band)", reading: "%B < 0: dÆ°á»›i dáº£i dÆ°á»›i; 0â€“1: trong dáº£i; > 1: trÃªn dáº£i trÃªn. Cáº§n káº¿t há»£p xu hÆ°á»›ng vÃ  khá»‘i lÆ°á»£ng." },
  { term: "EMA", meaning: "Trung bÃ¬nh Ä‘á»™ng Ä‘áº·t trá»ng sá»‘ lá»›n hÆ¡n cho giÃ¡ gáº§n hiá»‡n táº¡i.", formula: "EMAâ‚œ = Î±Priceâ‚œ + (1âˆ’Î±)EMAâ‚œâ‚‹â‚; Î± = 2/(N+1)", reading: "GiÃ¡ trÃªn EMA thÆ°á»ng thiÃªn tÄƒng; dÆ°á»›i EMA thÆ°á»ng thiÃªn giáº£m. Khoáº£ng cÃ¡ch quÃ¡ xa cÃ³ thá»ƒ bÃ¡o tráº¡ng thÃ¡i quÃ¡ cÄƒng." },
  { term: "Relative Strength (RS)", meaning: "So sÃ¡nh hiá»‡u suáº¥t cá»§a má»™t mÃ£ vá»›i chá»‰ sá»‘ tham chiáº¿u trong cÃ¹ng giai Ä‘oáº¡n.", formula: "RS = (1 + return mÃ£) / (1 + return chá»‰ sá»‘)", reading: "> 1: mÃ£ máº¡nh hÆ¡n thá»‹ trÆ°á»ng; < 1: yáº¿u hÆ¡n. RS tÄƒng Ä‘á»u Ä‘Ã¡ng tin hÆ¡n má»™t Ä‘iá»ƒm tÄƒng Ä‘Æ¡n láº»." },
  { term: "Breakout", meaning: "GiÃ¡ vÆ°á»£t vÃ¹ng cáº£n hoáº·c Ä‘á»‰nh trÆ°á»›c, thÆ°á»ng dÃ¹ng Ä‘á»ƒ nháº­n biáº¿t xu hÆ°á»›ng má»›i.", formula: "Price > resistance; xÃ¡c nháº­n thÆ°á»ng kÃ¨m Volume / Volume MA > 1", reading: "Tá»‘t hÆ¡n khi Ä‘Ã³ng cá»­a trÃªn cáº£n vÃ  khá»‘i lÆ°á»£ng tÄƒng. VÆ°á»£t cáº£n rá»“i quay xuá»‘ng nhanh cÃ³ thá»ƒ lÃ  breakout giáº£." },
  { term: "Order flow", meaning: "ChÃªnh lá»‡ch tÆ°Æ¡ng Ä‘á»‘i giá»¯a khá»‘i lÆ°á»£ng mua chá»§ Ä‘á»™ng vÃ  bÃ¡n chá»§ Ä‘á»™ng.", formula: "OF â‰ˆ (Buy active âˆ’ Sell active) / (Buy active + Sell active)", reading: "> 0: Ã¡p lá»±c mua; < 0: Ã¡p lá»±c bÃ¡n; gáº§n 0: cÃ¢n báº±ng. CÃ¡ch phÃ¢n loáº¡i lá»‡nh phá»¥ thuá»™c nguá»“n dá»¯ liá»‡u." },
  { term: "t-stat", meaning: "Äo há»‡ sá»‘ Æ°á»›c lÆ°á»£ng lá»›n bao nhiÃªu so vá»›i sai sá»‘ cá»§a chÃ­nh nÃ³.", formula: "t = coefficient / standard error", reading: "Quy Æ°á»›c |t| â‰¥ 2: cÃ³ Ã½ nghÄ©a thá»‘ng kÃª tÆ°Æ¡ng Ä‘á»‘i; |t| nhá»: chÆ°a Ä‘á»§ báº±ng chá»©ng. KhÃ´ng Ä‘á»“ng nghÄ©a cháº¯c cháº¯n cÃ³ lÃ£i." },
  { term: "RÂ²", meaning: "Tá»· lá»‡ biáº¿n Ä‘á»™ng cá»§a lá»£i nhuáº­n Ä‘Æ°á»£c mÃ´ hÃ¬nh giáº£i thÃ­ch trÃªn máº«u Ä‘Ã£ dÃ¹ng.", formula: "RÂ² = 1 âˆ’ SSE/SST", reading: "Tá»« 0 Ä‘áº¿n 1; cao hÆ¡n lÃ  khá»›p máº«u tá»‘t hÆ¡n, nhÆ°ng quÃ¡ cao trÃªn máº«u nhá» cÃ³ thá»ƒ lÃ  overfit." },
  { term: "Horizon", meaning: "Sá»‘ phiÃªn tá»« ngÃ y phÃ¡t tÃ­n hiá»‡u Ä‘áº¿n ngÃ y Ä‘o lá»£i nhuáº­n.", formula: "ReturnNh = Price(t+N) / Price(t) âˆ’ 1", reading: "3d pháº£n Ã¡nh ngáº¯n háº¡n; 5d/10d pháº£n Ã¡nh Ä‘á»™ bá»n dÃ i hÆ¡n. Khung 1d Ä‘Æ°á»£c áº©n khá»i so sÃ¡nh cháº¥t lÆ°á»£ng vÃ¬ nhiá»…u cao." },
  { term: "n (cá»¡ máº«u)", meaning: "Sá»‘ quan sÃ¡t há»£p lá»‡ dÃ¹ng Ä‘á»ƒ tÃ­nh chá»‰ sá»‘.", formula: "n = sá»‘ cáº·p (score, future return) há»£p lá»‡", reading: "n cÃ ng lá»›n thÆ°á»ng cÃ ng á»•n Ä‘á»‹nh. Vá»›i báº£ng ngÃ nh, n < 30 nÃªn xem lÃ  tham kháº£o tháº­n trá»ng." },
];

interface ICRow {
  config_version: string;
  factor: string;
  horizon: number;
  ic: number | null;
  n: number | null;
  computed_at: string | null;
  sample_kind?: "forward" | "retrospective_backfill";
}

function formatUpdatedAt(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short", timeZone: "Asia/Ho_Chi_Minh" }).format(date);
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
  groups, colLabel, nameOf, minN = 30, showSample = false,
}: {
  groups: BrkGroup[];
  colLabel: string;
  nameOf: (k: string) => string;
  minN?: number;
  showSample?: boolean;
}) {
  const rows = groups.filter((g) => (g.h.get(5)?.n ?? 0) >= minN);
  if (!rows.length) return <p className="text-xs text-[var(--color-muted)]">ChÆ°a Ä‘á»§ dá»¯ liá»‡u.</p>;
  return (
    <div className="table-scroll overflow-x-auto rounded-lg border border-[var(--color-border)]">
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
                  <td key={h} className="tabular min-w-[76px] cursor-help px-3 py-2 text-center" style={{ backgroundColor: bg, color: fg }} title={title}>
                    <div>{ic === null ? "â€”" : (ic >= 0 ? "+" : "") + ic.toFixed(3)}</div>
                    {showSample && c ? <div className="mt-0.5 text-[10px] opacity-70">n={c.n}</div> : null}
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
  const supabase = createCachedPublicClient("ic-metadata", DEFAULT_SCORING_VERSION);
  const [icResponse, backfillResponse, coverageResponse] = await Promise.all([
    supabase.from("v4_ic_metrics")
      .select("config_version, factor, horizon, ic, n, computed_at")
      .order("config_version", { ascending: false })
      .order("factor", { ascending: true })
      .order("horizon", { ascending: true }),
    supabase.from("v4_ic_backfill_metrics")
      .select("config_version, factor, horizon, ic, n, computed_at, sample_kind")
      .order("config_version", { ascending: false })
      .order("factor", { ascending: true })
      .order("horizon", { ascending: true }),
    supabase.from("v4_dashboard_version_summary")
      .select("scoring_version, signal_date_min, signal_date_max, signal_days, signal_rows, outcome_date_min, outcome_date_max, outcome_rows, latest_update")
      .order("scoring_version", { ascending: false }),
  ]);

  const forwardRows = ((icResponse.data ?? []) as ICRow[]).map((row) => ({ ...row, sample_kind: "forward" as const }));
  const historicalRows = (backfillResponse.data ?? []) as ICRow[];
  // Never mix retrospective and forward evidence. Forward wins as soon as a
  // version has enough independently matured observations to produce IC.
  const rows = REVIEW_VERSIONS.flatMap((version) => {
    const forward = forwardRows.filter((row) => row.config_version === version);
    return forward.length
      ? forward
      : historicalRows.filter((row) => row.config_version === version);
  });
  const coverageRows = (coverageResponse.data ?? []) as Array<{ scoring_version: string; signal_date_min: string | null; signal_date_max: string | null; signal_days: number; signal_rows: number; outcome_date_min: string | null; outcome_date_max: string | null; outcome_rows: number; latest_update: string | null }>;
  const officialVersions = REVIEW_VERSIONS.filter((version) => rows.some((row) => row.config_version === version));
  const curVer = officialVersions.includes(DEFAULT_SCORING_VERSION) ? DEFAULT_SCORING_VERSION : (officialVersions[0] ?? DEFAULT_SCORING_VERSION);
  const curHasIC = rows.some((row) => row.config_version === curVer);
  const currentClient = createCachedPublicClient("ic", curVer);

  // Fetch every version independently so each result has its own cache TTL/tag and
  // no request can be truncated by PostgREST's 1,000-row response limit.
  const [industryBatchRes, perVersionRows] = await Promise.all([
    currentClient.from("v4_ic_industry_batch").select("batch_id, data_asof, computed_at").eq("status", "ready").order("computed_at", { ascending: false }).limit(1).maybeSingle(),
    Promise.all(officialVersions.map(async (version) => {
      const client = createCachedPublicClient("ic", version);
      const marginalRes = await client.from("v4_marginal_ic")
        .select("version, indicator, factor, horizon, coef, tstat, univar_ic, n")
        .eq("version", version);
      return { version, marginalRows: marginalRes.data ?? [] };
    })),
  ]);

  const industryResults = industryBatchRes.data
    ? await Promise.all(officialVersions.map(async (version) => {
        const client = createCachedPublicClient("ic", version);
        const result = await client
          .from("v4_ic_industry_metrics")
          .select("version, factor, industry, horizon, ic, n")
          .eq("batch_id", industryBatchRes.data!.batch_id)
          .eq("version", version)
          .order("factor", { ascending: true })
          .order("industry", { ascending: true })
          .order("horizon", { ascending: true });
        return { version, data: result.data ?? [], error: result.error?.message ?? null };
      }))
    : officialVersions.map((version) => ({
        version,
        data: [],
        error: industryBatchRes.error?.message ?? null,
      }));

  const factorVerRows = rows.map((row) => ({
    version: row.config_version, factor: row.factor, horizon: row.horizon, ic: row.ic, n: row.n, sampleKind: row.sample_kind,
  })) as FactorVerRow[];
  const marginalRows = perVersionRows.flatMap((result) => result.marginalRows) as (MargRow & { version: string })[];
  const toBrk = (arr: Record<string, unknown>[], keyField: string): BrkRow[] =>
    arr.map((row) => ({
      key: String(row[keyField]),
      horizon: Number(row.horizon),
      ic: row.ic == null ? null : Number(row.ic),
      n: Number(row.n),
    }));
  const indGroups = groupBrk(toBrk(
    marginalRows
      .filter((row) => row.version === curVer)
      .map((row) => ({ indicator: row.indicator, horizon: row.horizon, ic: row.univar_ic, n: row.n })),
    "indicator",
  ));

  const indByName = new Map(indGroups.map((group) => [group.name, group]));
  const indByFactor = FACTOR_GROUPS.map((factorGroup) => ({
    key: factorGroup.key,
    label: factorGroup.label,
    members: factorGroup.members.map((member) => indByName.get(member)).filter((group): group is BrkGroup => !!group),
  })).filter((factor) => factor.members.length);

  const industryByVersion = industryResults.map((result) => ({
    version: result.version,
    error: result.error,
    factors: FACTOR_ORDER.map((factor) => ({
      factor,
      groups: groupBrk(toBrk(
        (result.data as Record<string, unkn×=¶‰ËkºwµçQ•áĞµÉ¥¡ĞÑ…‰Õ±…Èˆùí9Õµ‰•È¡É½Ü¹½ÕÑ½µ•}É½İÌ¤¹Ñ½1½…±•MÑÉ¥¹œ ‰Ù¤µY8ˆ¥ôğ½Ñøğ½ÑÈø¥ôğ½Ñ‰½‘äø(€€€€€€€€€€€€ğ½Ñ…‰±”ø(€€€€€€€€€€ğ½‘¥Øø(€€€€€€€€ğ½‘•Ñ…¥±Ìø(€€€€€€¤€è¹Õ±±ô(€€€€€íÕÉY•È€ü€ (€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰…Éµˆ´Ğ™±•à™±•àµİÉ…À¥Ñ•µÌµ•¹Ñ•È…Àµà´È…Àµä´ÄÀ´È¸ÔÑ•áĞµlÄÍÁátˆø(€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰É½Õ¹‘•µµ‰œµmÙ…È ´µ½±½Èµ…•¹Ğ¥tÁà´ÈÁä´À¸ÔÑ•áĞµlÄÅÁát™½¹ĞµÍ•µ¥‰½±Ñ•áĞµİ¡¥Ñ”ˆù!'†î8S†ê$ğ½ÍÁ…¸ø(€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰™½¹Ğµµ½¹¼™½¹ĞµÍ•µ¥‰½±ˆùÍ½É¥¹œíÕÉY•Éôğ½ÍÁ…¸ø(€€€€€€€€€íÉ½İÌ¹Í½µ” ¡É½Ü¤€ôøÉ½Ü¹½¹™¥}Ù•ÉÍ¥½¸€ôôôÕÉY•È€˜˜É½Ü¹Í…µÁ±•}­¥¹€ôôô€‰É•ÑÉ½ÍÁ•Ñ¥Ù•}‰…­™¥±°ˆ¤€ü€ (€€€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰Ñ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆûŠP%¡§†î¸Ó†ê…¤³€€ñˆ±…ÍÍ9…µ”ô‰Ñ•áĞµmÙ…È ´µ½±½Èµ¥¹¬¥tˆù‰…­™¥±°³†î- Ï†î´ğ½ˆøÓ†î¬½ÕÑ½µ”ØĞ¸Äàì£Á„Á£†ê¤¯†êıĞÅ×†êŒ™½Éİ…ÉƒG†îeŒ³†êµÀ¸ğ½ÍÁ…¸ø(€€€€€€€€€€¤€èÕÉ!…Í%€ü€ (€€€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰Ñ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆûŠP%‹©¸“Ã†îm¤€£G…¹ “†ê•Ô€™±‘ÅÕ¼í¡§†î¸Ó†ê…¤™É‘ÅÕ¼ì¤¸ğ½ÍÁ…¸ø(€€€€€€€€€€¤€è€ (€€€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰Ñ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆø(€€€€€€€€€€€€€ƒŠP€ñˆ±…ÍÍ9…µ”ô‰Ñ•áĞµmÙ…È ´µ½±½Èµ¥¹¬¥tˆù£Á„ƒG†îœ“†î¼±§†îÔ™½Éİ…ÉƒG†îÓµ¹ %ğ½ˆø¸7†î]¤³†ê¸ƒG†îU¤Ù•ÉÍ¥½¸³€É•Í•Ğ(€€€€€€€€€€€€€™½Éİ…ÉµÙ…±¥‘…Ñ¥½¸ƒŠH†ê¸Óµ ±×†îä½ÕÑ½µ•ÌÛ¤Á¡§©¸Ë†îM¤•Ù…±Õ…Ñ½È€¡AåÑ¡½¸¤·†îm¤¡¤%¸†ê¹œ“Ã†îm¤³€…Œ(€€€€€€€€€€€€€Ù•ÉÍ¥½¸¤ƒGŒƒG†îœ·†ê­Ô°“å¹œƒG†îÑ¡…´¡§†êıÔ¸(€€€€€€€€€€€€ğ½ÍÁ…¸ø(€€€€€€€€€€¥ô(€€€€€€€€ğ½‘¥Øø(€€€€€€¤€è¹Õ±±ô(€€€€€íÙ•É1¥ÍĞ¹µ…À ¡Ù•ÉÍ¥½¸¤€ôø€ (€€€€€€€€ñ…Ñ½É%Q…‰±”(€€€€€€€€€­•äõíÙ•ÉÍ¥½¹ô(€€€€€€€€€Ù•ÉÍ¥½¸õíÙ•ÉÍ¥½¹ô(€€€€€€€€€ÕÉY•ÈõíÕÉY•Éô(€€€€€€€€€½™™¥¥…°õíÉ½İÌ¹™¥±Ñ•È ¡É½Ü¤€ôøÉ½Ü¹½¹™¥}Ù•ÉÍ¥½¸€ôôôÙ•ÉÍ¥½¸¥ô(€€€€€€€€€µ…É¥¹…°õíµ…É¥¹…±I½İÌ¹™¥±Ñ•È ¡É½Ü¤€ôøÉ½Ü¹Ù•ÉÍ¥½¸€ôôôÙ•ÉÍ¥½¸¥ô(€€€€€€€€€ÕÁ‘…Ñ•‘ĞõíÕÁ‘…Ñ•‘Ñ	åY•ÉÍ¥½¸¹•Ğ¡Ù•ÉÍ¥½¸¥ô(€€€€€€€€€‘…Ñ…M½Á”õíÉ½İÌ¹™¥¹ ¡É½Ü¤€ôøÉ½Ü¹½¹™¥}Ù•ÉÍ¥½¸€ôôôÙ•ÉÍ¥½¸¤ü¹Í…µÁ±•}­¥¹‘ô(€€€€€€€€¼ø(€€€€€€¤¥ô(€€€€€€ñÍ•Ñ¥½¸±…ÍÍ9…µ”ô‰…Éµˆ´ØÀ´ÌÍ´éÀ´Ğˆø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µˆ´Ì™±•à™±•àµİÉ…À¥Ñ•µÌµÍÑ…ÉĞ©ÕÍÑ¥™äµ‰•Ñİ••¸…À´Èˆø(€€€€€€€€€€ñ‘¥Øø(€€€€€€€€€€€€ñ È±…ÍÍ9…µ”ô‰Ñ•áĞµÍ´™½¹ĞµÍ•µ¥‰½±ˆù%Ñ¡•¼¹Ÿ¹ Û€¹£Í´Í½É¥¹œğ½ Èø(€€€€€€€€€€€€ñÀ±…ÍÍ9…µ”ô‰µĞ´ÄÑ•áĞµlÄÉÁátÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆø(€€€€€€€€€€€€€7†î]¤Í½É¥¹œÙ•ÉÍ¥½¸ƒGÃ†îŒÓ… Ñ¡•¼ƒE§†î´Ó†îU¹œÛ€€Ø…Ñ•½Éä¸7†î|Ù•ÉÍ¥½¸°Í…ÔƒGÌ·†î|…Ñ•½Éä†ê¸á•´¸(€€€€€€€€€€€€ğ½Àø(€€€€€€€€€€ğ½‘¥Øø(€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰É½Õ¹‘•µµ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tÁà´ÈÁä´ÄÑ•áĞµlÄÅÁátÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆø(€€€€€€€€€€€%MÁ•…Éµ…¸ƒ
Ü¸€ô†î„·†ê­Ô(€€€€€€€€€€ğ½ÍÁ…¸ø(€€€€€€€€ğ½‘¥Øø((€€€€€€€í½™™¥¥…±Y•ÉÍ¥½¹Ì¹±•¹Ñ €ü€ (€€€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰ÍÁ…”µä´Èˆø(€€€€€€€€€€€í¥¹‘ÕÍÑÉå	åY•ÉÍ¥½¸¹µ…À ¡Ù•ÉÍ¥½¹…Ñ„¤€ôø€ (€€€€€€€€€€€€€€ñ‘•Ñ…¥±Ì(€€€€€€€€€€€€€€€­•äõíÙ•ÉÍ¥½¹…Ñ„¹Ù•ÉÍ¥½¹ô(€€€€€€€€€€€€€€€±…ÍÍ9…µ”ô‰É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥t‰œµmÙ…È ´µ½±½ÈµÍÕÉ™…”¥tÀ´È¸Ôˆ(€€€€€€€€€€€€€€€½Á•¸õíÙ•ÉÍ¥½¹…Ñ„¹Ù•ÉÍ¥½¸€ôôôÕÉY•Éô(€€€€€€€€€€€€€€ø(€€€€€€€€€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰™±•àÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”¥Ñ•µÌµ•¹Ñ•È©ÕÍÑ¥™äµ‰•Ñİ••¸…À´È™½¹Ğµµ½¹¼Ñ•áĞµlÄÍÁát™½¹ĞµÍ•µ¥‰½±ˆø(€€€€€€€€€€€€€€€€€€ñÍÁ…¸ùÍ½É¥¹œíÙ•ÉÍ¥½¹…Ñ„¹Ù•ÉÍ¥½¹õíÙ•ÉÍ¥½¹…Ñ„¹Ù•ÉÍ¥½¸€ôôôÕÉY•È€ü€ˆ€¡¡§†î¸Ó†ê…¤¤ˆ€è€ˆ‰ôğ½ÍÁ…¸ø(€€€€€€€€€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰™½¹ĞµÍ…¹ÌÑ•áĞµlÄÅÁát™½¹Ğµ¹½Éµ…°Ñ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùíÙ•ÉÍ¥½¹…Ñ„¹™…Ñ½ÉÌ¹±•¹Ñ¡ô…Ñ•½Éäğ½ÍÁ…¸ø(€€€€€€€€€€€€€€€€ğ½ÍÕµµ…Éäø(€€€€€€€€€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´ÈÍÁ…”µä´Èˆø(€€€€€€€€€€€€€€€€€íÙ•ÉÍ¥½¹…Ñ„¹•ÉÉ½È€ü€ (€€€€€€€€€€€€€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰É½Õ¹‘•µµ‰½É‘•È‰½É‘•Èµ‘…Í¡•‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tÁà´ÌÁä´ĞÑ•áĞµ•¹Ñ•ÈÑ•áĞµáÌÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆø(€€€€€€€€€€€€€€€€€€€€€-£Ñ¹œÓ†ê¤ƒGÃ†îŒ“†î¼±§†îÔ†î„Í½É¥¹œíÙ•ÉÍ¥½¹…Ñ„¹Ù•ÉÍ¥½¹ô¸YÕ¤³É¹œÓ†ê¤³†ê…¤ÑÉ…¹œ¸(€€€€€€€€€€€€€€€€€€€€ğ½‘¥Øø(€€€€€€€€€€€€€€€€€€¤€èÙ•ÉÍ¥½¹…Ñ„¹™…Ñ½ÉÌ¹µ…À ¡™…Ñ½É…Ñ„¤€ôøì(€€€€€€€€€€€€€€€€€€€½¹ÍĞ¥¹™¼€ôQ=I}%9=m™…Ñ½É…Ñ„¹™…Ñ½Étì(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸€ (€€€€€€€€€€€€€€€€€€€€€€ñ‘•Ñ…¥±Ì(€€€€€€€€€€€€€€€€€€€€€€€­•äõí™…Ñ½É…Ñ„¹™…Ñ½Éô(€€€€€€€€€€€€€€€€€€€€€€€±…ÍÍ9…µ”ô‰É½Õ¹‘•µµ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥t‰œµ‰±…¬½lÀ¸ÀÄÕtÀ´È‘…É¬é‰œµİ¡¥Ñ”½lÀ¸ÀÉtˆ(€€€€€€€€€€€€€€€€€€€€€€€½Á•¸õí™…Ñ½É…Ñ„¹™…Ñ½È€ôôô€‰Í½É•}ÑÉ…‘”‰ô(€€€€€€€€€€€€€€€€€€€€€€ø(€€€€€€€€€€€€€€€€€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰™±•àÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”¥Ñ•µÌµ•¹Ñ•È©ÕÍÑ¥™äµ‰•Ñİ••¸…À´ÈÑ•áĞµlÄÉÁát™½¹ĞµÍ•µ¥‰½±ˆø(€€€€€€€€€€€€€€€€€€€€€€€€€€ñÍÁ…¸ùí¥¹™¼ü¹±…‰•°€üü™…Ñ½É…Ñ„¹™…Ñ½Éôğ½ÍÁ…¸ø(€€€€€€€€€€€€€€€€€€€€€€€€€€ñÍÁ…¸±…ÍÍ9…µ”ô‰™½¹Ğµ¹½Éµ…°Ñ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùí™…Ñ½É…Ñ„¹É½ÕÁÌ¹±•¹Ñ¡ô¹Ÿ¹ ğ½ÍÁ…¸ø(€€€€€€€€€€€€€€€€€€€€€€€€ğ½ÍÕµµ…Éäø(€€€€€€€€€€€€€€€€€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Èˆø(€€€€€€€€€€€€€€€€€€€€€€€€€€ñ	É•…­‘½İ¹Q…‰±”É½ÕÁÌõí™…Ñ½É…Ñ„¹É½ÕÁÍô½±1…‰•°ô‰9Ÿ¹ ˆ¹…µ•=˜õì¡­•ä¤€ôø­•åôµ¥¹8õìÌÁôÍ¡½İM…µÁ±”€¼ø(€€€€€€€€€€€€€€€€€€€€€€€€ğ½‘¥Øø(€€€€€€€€€€€€€€€€€€€€€€ğ½‘•Ñ…¥±Ìø(€€€€€€€€€€€€€€€€€€€€¤ì(€€€€€€€€€€€€€€€€€ô¥ô(€€€€€€€€€€€€€€€€€€ñÀ±…ÍÍ9…µ”ô‰Ñ•áĞµlÄÅÁátÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆø(€€€€€€€€€€€€€€€€€€€ƒC‰ä³€%Á½½±•ƒG†îÍ¼ÓÃ…¹œƒG†îE¤§†î½„¹Ÿ¹ ½…Ñ•½Éä¸Q£†êµ¸ÑË†î5¹œÛ†îm¤ƒĞÌ¸€™±Ğì€ÌÀì%½™™¥¥…°Ñ¡•¼¹ŸäÛ†ê­¸»†êÅ´ƒ†î|‹†ê¹œÍ½É¥¹œÁ£µ„ÑË©¸¸(€€€€€€€€€€€€€€€€€€ğ½Àø(€€€€€€€€€€€€€€€€ğ½‘¥Øø(€€€€€€€€€€€€€€ğ½‘•Ñ…¥±Ìø(€€€€€€€€€€€€¤¥ô(€€€€€€€€€€ğ½‘¥Øø(€€€€€€€€¤€è€ (€€€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•Èµ‘…Í¡•‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tÁà´ÌÁä´ØÑ•áĞµ•¹Ñ•ÈÑ•áĞµáÌÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆø(€€€€€€€€€€€£Á„Ì%Ñ¡•¼¹Ÿ¹ ¡¼…ŒÍ½É¥¹œÙ•ÉÍ¥½¸Ì%½™™¥¥…°¸(€€€€€€€€€€ğ½‘¥Øø(€€€€€€€€¥ô(€€€€€€ğ½Í•Ñ¥½¸ø(€€€€€€ñ‘•Ñ…¥±Ì±…ÍÍ9…µ”ô‰…Éµˆ´ĞÀ´Ìˆø(€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰ÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”Ñ•áĞµÍ´™½¹ĞµÍ•µ¥‰½±ˆù… ƒG†î5Œ‹†ê¹œ%ğ½ÍÕµµ…Éäø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Ì½Ù•É™±½Üµàµ…ÕÑ¼É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆø(€€€€€€€€€€ñÑ…‰±”±…ÍÍ9…µ”ô‰Üµ™Õ±°µ¥¸µÜµlØĞÁÁátÑ•áĞµáÌˆø(€€€€€€€€€€€€ñÑ¡•…±…ÍÍ9…µ”ô‰‰œµ‰±…¬½lÀ¸ÀÍtÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥t‘…É¬é‰œµİ¡¥Ñ”½lÀ¸ÀÍtˆøñÑÈøñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù-£…¤¹§†î´ğ½Ñ øñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù… ¡§†îÔğ½Ñ øğ½ÑÈøğ½Ñ¡•…ø(€€€€€€€€€€€€ñÑ‰½‘äø(€€€€€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆù%ğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùSÃ…¹œÅÕ…¸£†ê…¹œMÁ•…Éµ…¸§†î½„ƒE§†î´¹£‰¸Ó†îD­¡¤Á£…ĞÓµ¸¡§†îÔÛ€³†î¤¹¡×†êµ¸Ñ£†îÅŒÓ†êüÍ…Ô8Á¡§©¸¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆûC†îd·†ê…¹ ñ%ğğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùÃ†îm¤€À°ÀÈèŸ†ê¸¹£À­£Ñ¹œ“†îÄ‹…¼ì€À°ÀËŠLÀ°ÀÔèÌÓµ¸¡§†îÔì€À°À×ŠLÀ°ÄÀèÓ†îEĞìÑË©¸€À°ÄÀèË†ê•Ğ·†ê…¹ Û€†ê¸­§†î´ÑÉ„†î„·†ê­Ô¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆù†ê•ÔÛ€·Ôğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆøñÍÁ…¸±…ÍÍ9…µ”ô‰™½¹ĞµÍ•µ¥‰½±Ñ•áĞµmÙ…È ´µ½±½Èµ‰Õä¥tˆùÃ…¹œ°·Ôá…¹ ğ½ÍÁ…¸øè“†îÄ‹…¼Ñ¡×†êµ¸¸€ñÍÁ…¸±…ÍÍ9…µ”ô‰™½¹ĞµÍ•µ¥‰½±Ñ•áĞµmÙ…È ´µ½±½ÈµÍ•±°¥tˆû	´°·ÔƒG†î<ğ½ÍÁ…¸øè“†îÄ‹…¼¹£†î- ¸7ÔƒG†êµ´£…¸¹£¥„³€ñ%ğ³†îm¸£…¸¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆøÍ€¼€Õ€¼€ÄÁğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆù3†î¤¹¡×†êµ¸ƒGÃ†îŒƒE¼Í…Ô€Ì°€Ô¡¿†êİŒ€ÄÀÁ¡§©¸ƒG†îÁ£‰¸‰§†îĞ­£†êŒ»¹œ“†îÄ‹…¼¹Ÿ†ê½¸Û€“¤£†ê…¸¸-¡Õ¹œ€ÄÁ¡§©¸­£Ñ¹œ“å¹œÑÉ½¹œÁ£†ê¸Í¼Ï…¹ £†ê•Ğ³Ã†î¹œÛ°“†î¹¡§†îÔ¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆù†î„·†ê­Ô¸ğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆù¸¹£†î<³´%“†î¹¡§†îÔ¸ƒ½ÔÑ§©¸¯†êıĞÅ×†êŒÌ¸³†îm¸Û€ƒ†îU¸ƒG†î-¹ ÅÕ„¹¡§†îÔ­¡Õ¹œÁ¡§©¸¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆùM½É¥¹œÙ•ÉÍ¥½¸ğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆù7†î]¤Ù•ÉÍ¥½¸ƒGÃ†îŒ™½Éİ…ÉµÙ…±¥‘…Ñ¥½¸É§©¹œ¸-¡¤ƒG†îU¤Ù•ÉÍ¥½¸°†ê¸Óµ ³¥ä½ÕÑ½µ•Ì·†îm¤ÑËÃ†îmŒ­¡¤¯†êıĞ±×†êµ¸¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆù9×†îM¸Ï†îD±§†îÔğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆù%£µ¹ Ñ£†î¥Œ‘¼•Ù…±Õ…Ñ½ÈAåÑ¡½¸Óµ¹ ÑË©¸“†î¼±§†îÔÓÃ…¹œ±…¤Ñ£†îÅŒ°­£Ñ¹œÁ£†ê¤‰…­Ñ•ÍĞ¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€€€ğ½Ñ‰½‘äø(€€€€€€€€€€ğ½Ñ…‰±”ø(€€€€€€€€ğ½‘¥Øø(€€€€€€ğ½‘•Ñ…¥±Ìø((€€€€€€ñ‘•Ñ…¥±Ì±…ÍÍ9…µ”ô‰…Éµˆ´ĞÀ´Ìˆø(€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰ÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”Ñ•áĞµÍ´™½¹ĞµÍ•µ¥‰½±ˆût¹£¥„Ó†î­¹œ¹£‰¸Ó†îDğ½ÍÕµµ…Éäø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Ì½Ù•É™±½Üµàµ…ÕÑ¼É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆø(€€€€€€€€€€ñÑ…‰±”±…ÍÍ9…µ”ô‰Üµ™Õ±°µ¥¸µÜµlÜØÁÁátÑ•áĞµáÌˆø(€€€€€€€€€€€€ñÑ¡•…±…ÍÍ9…µ”ô‰‰œµ‰±…¬½lÀ¸ÀÍtÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥t‘…É¬é‰œµİ¡¥Ñ”½lÀ¸ÀÍtˆøñÑÈøñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù7Œ¹£‰¸Ó†îDğ½Ñ øñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™ĞˆùS©¸ğ½Ñ øñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù§†î¸§†ê¤ğ½Ñ øñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù£†î$‹…¼Ñ£¹ Ù§©¸ğ½Ñ øğ½ÑÈøğ½Ñ¡•…ø(€€€€€€€€€€€€ñÑ‰½‘äùíQ=I}=IH¹™¥±Ñ•È ¡­•ä¤€ôøQ=I}%9=m­•åt¤¹µ…À ¡­•ä¤€ôøì½¹ÍĞ¥¹™¼€ôQ=I}%9=m­•åtìÉ•ÑÕÉ¸€ (€€€€€€€€€€€€€€ñÑÈ­•äõí­•åô±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥t…±¥¸µÑ½ÀˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ½¹¼™½¹ĞµÍ•µ¥‰½±ˆùí­•åôğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆùí¥¹™¼¹±…‰•±ôğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùí¥¹™¼¹‘•Íôğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùí¥¹™¼¹µ•µ‰•ÉÌ¹±•¹Ñ €ü¥¹™¼¹µ•µ‰•ÉÌ¹©½¥¸ ˆƒ
Ü€ˆ¤€è€‹ŠP‰ôğ½Ñøğ½ÑÈø(€€€€€€€€€€€€¤ìô¥ôğ½Ñ‰½‘äø(€€€€€€€€€€ğ½Ñ…‰±”ø(€€€€€€€€ğ½‘¥Øø(€€€€€€ğ½‘•Ñ…¥±Ìø((€€€€€€ñ‘•Ñ…¥±Ì±…ÍÍ9…µ”ô‰…Éµˆ´ĞÀ´Ìˆø(€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰ÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”Ñ•áĞµÍ´™½¹ĞµÍ•µ¥‰½±ˆùM¼Ï…¹ ¹£‰¸Ó†îDÅÕ„Ó†ê•Ğ†êŒÙ•ÉÍ¥½¸ğ½ÍÕµµ…Éäø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Ì½Ù•É™±½Üµàµ…ÕÑ¼É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ…‰±”±…ÍÍ9…µ”ô‰Üµ™Õ±°µ¥¸µÜµlØĞÁÁátÑ•áĞµáÌˆøñÑ¡•…±…ÍÍ9…µ”ô‰‰œµ‰±…¬½lÀ¸ÀÍtÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥t‘…É¬é‰œµİ¡¥Ñ”½lÀ¸ÀÍtˆøñÑÈøñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù;†îe¤‘Õ¹œğ½Ñ øñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù… Ï†î´“†î•¹œğ½Ñ øğ½ÑÈøğ½Ñ¡•…øñÑ‰½‘äø(€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆù7†î•ŒƒGµ ğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùS±´¹£‰¸Ó†îD“Ã…¹œƒ†îU¸ƒG†î-¹ ÅÕ„¹¡§†îÔÙ•ÉÍ¥½¸ƒG†î‰¸¹£†ê½ŒÓ¹œÑË†î5¹œÏ†îDì¹£‰¸Ó†îDƒ‰´‘…¤“†êÍ¹œƒG†î‰¸¹£†ê½Œ§†ê´¡¿†êİŒƒG†ê¼ÑË†î5¹œÏ†îD¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆùA£†ê…´Ù¤ğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆû¿†îmŒ³Ã†î¹œÁ½½±•ÑË©¸…ŒÙ•ÉÍ¥½¸ÌƒG†îœ·†ê­Ôì“å¹œƒG†îÑ¡…´¡§†êıÔ¸O†îD£µ¹ Ñ£†î¥Œ»†êÅ´ƒ†î|‹†ê¹œÍ½É¥¹œÁ£µ„ÑË©¸¸ğ½Ñøğ½ÑÈø(€€€€€€€€ğ½Ñ‰½‘äøğ½Ñ…‰±”øğ½‘¥Øø(€€€€€€ğ½‘•Ñ…¥±Ìø((€€€€€€ñ‘•Ñ…¥±Ì±…ÍÍ9…µ”ô‰…Éµˆ´ĞÀ´Ìˆø(€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰ÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”Ñ•áĞµÍ´™½¹ĞµÍ•µ¥‰½±ˆù%Ñ¡•¼£†î$Ï†îD½¸ğ½ÍÕµµ…Éäø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Ì½Ù•É™±½Üµàµ…ÕÑ¼É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ…‰±”±…ÍÍ9…µ”ô‰Üµ™Õ±°µ¥¸µÜµlØĞÁÁátÑ•áĞµáÌˆøñÑ¡•…±…ÍÍ9…µ”ô‰‰œµ‰±…¬½lÀ¸ÀÍtÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥t‘…É¬é‰œµİ¡¥Ñ”½lÀ¸ÀÍtˆøñÑÈøñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù;†îe¤‘Õ¹œğ½Ñ øñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù… ƒG†î5Œğ½Ñ øğ½ÑÈøğ½Ñ¡•…øñÑ‰½‘äø(€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆù9£Í´“†î¼±§†îÔğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆù…Œ£†î$‹…¼Ñ£¹ Ù§©¸ƒGÃ†îŒ½´Ñ¡•¼¹£Í´¹£‰¸Ó†îD¹£Àµ•…¹}É•Ù•ÉÍ¥½¸°‰É•…­½ÕĞ°™±½ÜÛ€…Œ¹£Í´É¸³†ê…¤¸ğ½Ñøğ½ÑÈø(€€€€€€€€€€ñÑÈ±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ•‘¥Õ´ˆût¹£¥„ğ½ÑøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùa…¹ ³€£†î$‹…¼“†îÄ‹…¼Ñ¡×†êµ¸°ƒG†î<³€“†îÄ‹…¼¹£†î- ¸ƒC‰ä³€ƒÃ†îmŒ³Ã†î¹œMÁ•…Éµ…¸Á½½±•Ñ¿¸¯†îÌƒG†îÑ¡…´¡§†êıÔìË¨¡×†îeĞ³©¸ƒĞƒG†îá•´¸¸ğ½Ñøğ½ÑÈø(€€€€€€€€ğ½Ñ‰½‘äøğ½Ñ…‰±”øğ½‘¥Øø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Ì™±•à™±•àµ½°…À´Ìˆùí¥¹‘	å…Ñ½È¹µ…À ¡™…Ñ½È¤€ôø€ (€€€€€€€€€€ñ‘¥Ø­•äõí™…Ñ½È¹­•åôøñ‘¥Ø±…ÍÍ9…µ”ô‰µˆ´ÄÑ•áĞµlÄÍÁát™½¹ĞµÍ•µ¥‰½±ˆùí™…Ñ½È¹±…‰•±ô€ñÍÁ…¸±…ÍÍ9…µ”ô‰™½¹Ğµµ½¹¼Ñ•áĞµlÄÅÁát™½¹Ğµ¹½Éµ…°Ñ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùí™…Ñ½È¹­•åôğ½ÍÁ…¸øğ½‘¥Øøñ	É•…­‘½İ¹Q…‰±”É½ÕÁÌõí™…Ñ½È¹µ•µ‰•ÉÍô½±1…‰•°ô‰£†î$‹…¼ˆ¹…µ•=˜õì¡­•ä¤€ôøÍ¥¹…±9…µ”¡­•ä¥ôµ¥¹8õìÄÀÁô€¼øğ½‘¥Øø(€€€€€€€€¤¥ôğ½‘¥Øø(€€€€€€ğ½‘•Ñ…¥±Ìø((€€€€€€ñ‘•Ñ…¥±Ì±…ÍÍ9…µ”ô‰…Éµˆ´ØÀ´Ìˆø(€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰ÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”Ñ•áĞµÍ´™½¹ĞµÍ•µ¥‰½±ˆùO†îD³Ã†î¹œ·†ê­ÔÑ¡•¼Í½É¥¹œÙ•ÉÍ¥½¸ğ½ÍÕµµ…Éäø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Ì½Ù•É™±½Üµàµ…ÕÑ¼É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ…‰±”±…ÍÍ9…µ”ô‰Üµ™Õ±°Ñ•áĞµáÌˆøñÑ¡•…±…ÍÍ9…µ”ô‰‰œµ‰±…¬½lÀ¸ÀÍtÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥t‘…É¬é‰œµİ¡¥Ñ”½lÀ¸ÀÍtˆøñÑÈøñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™ĞˆùY•ÉÍ¥½¸ğ½Ñ ùí!=I%i=9L¹µ…À ¡ ¤€ôø€ñÑ ­•äõí¡ô±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµÉ¥¡Ğˆùí¡ôÁ¡§©¸ğ½Ñ ø¥ôğ½ÑÈøğ½Ñ¡•…øñÑ‰½‘äùíÍ…µÁ±•	åY•ÉÍ¥½¸¹µ…À ¡ìÙ•ÉÍ¥½¸°‰å!½É¥é½¸ô¤€ôø€ñÑÈ­•äõíÙ•ÉÍ¥½¹ô±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆøñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ½¹¼ˆùíÙ•ÉÍ¥½¹õíÙ•ÉÍ¥½¸€ôôôÕÉY•È€ü€ˆ€¡¡§†î¸Ó†ê…¤¤ˆ€è€ˆ‰ôğ½Ñùí!=I%i=9L¹µ…À ¡ ¤€ôø€ñÑ­•äõí¡ô±…ÍÍ9…µ”ô‰Ñ…‰Õ±…ÈÁà´ÌÁä´ÈÑ•áĞµÉ¥¡Ğˆùí‰å!½É¥é½¸¹•Ğ¡ ¤ü¹Ñ½1½…±•MÑÉ¥¹œ ¤€üü€‹ŠP‰ôğ½Ñø¥ôğ½ÑÈø¥ôğ½Ñ‰½‘äøğ½Ñ…‰±”øğ½‘¥Øø(€€€€€€ğ½‘•Ñ…¥±Ìø(€€€€€€ñ‘•Ñ…¥±Ì±…ÍÍ9…µ”ô‰…Éµˆ´ØÀ´Ìˆø(€€€€€€€€ñÍÕµµ…Éä±…ÍÍ9…µ”ô‰ÕÉÍ½ÈµÁ½¥¹Ñ•ÈÍ•±•Ğµ¹½¹”Ñ•áĞµÍ´™½¹ĞµÍ•µ¥‰½±ˆùQ¡×†êµĞ¹Ÿ†î¼¡Õç©¸·Ñ¸Û€… ƒG†î5Œğ½ÍÕµµ…Éäø(€€€€€€€€ñ‘¥Ø±…ÍÍ9…µ”ô‰µĞ´Ì½Ù•É™±½Üµàµ…ÕÑ¼É½Õ¹‘•µ±œ‰½É‘•È‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥tˆø(€€€€€€€€€€ñÑ…‰±”±…ÍÍ9…µ”ô‰Üµ™Õ±°µ¥¸µÜµläàÁÁátÑ•áĞµáÌˆø(€€€€€€€€€€€€ñÑ¡•…±…ÍÍ9…µ”ô‰‰œµ‰±…¬½lÀ¸ÀÍtÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥t‘…É¬é‰œµİ¡¥Ñ”½lÀ¸ÀÍtˆø(€€€€€€€€€€€€€€ñÑÈø(€€€€€€€€€€€€€€€€ñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™ĞˆùQ¡×†êµĞ¹Ÿ†î¼ğ½Ñ ø(€€€€€€€€€€€€€€€€ñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™ĞˆûC†î-¹ ¹£¥„“†î¡§†îÔğ½Ñ ø(€€€€€€€€€€€€€€€€ñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™ĞˆùÑ¹œÑ£†î¥Œ„‹†ê¸ğ½Ñ ø(€€€€€€€€€€€€€€€€ñÑ ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµ±•™Ğˆù… ƒG†î5Œ€¼Ó†îEĞ€¼ã†ê•Ôğ½Ñ ø(€€€€€€€€€€€€€€ğ½ÑÈø(€€€€€€€€€€€€ğ½Ñ¡•…ø(€€€€€€€€€€€€ñÑ‰½‘äø(€€€€€€€€€€€€€íQ!9%1}QI5L¹µ…À ¡¥Ñ•´¤€ôø€ (€€€€€€€€€€€€€€€€ñÑÈ­•äõí¥Ñ•´¹Ñ•Éµô±…ÍÍ9…µ”ô‰‰½É‘•ÈµĞ‰½É‘•ÈµmÙ…È ´µ½±½Èµ‰½É‘•È¥t…±¥¸µÑ½Àˆø(€€€€€€€€€€€€€€€€€€ñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹ĞµÍ•µ¥‰½±ˆùí¥Ñ•´¹Ñ•Éµôğ½Ñø(€€€€€€€€€€€€€€€€€€ñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùí¥Ñ•´¹µ•…¹¥¹ôğ½Ñø(€€€€€€€€€€€€€€€€€€ñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´È™½¹Ğµµ½¹¼Ñ•áĞµlÄÅÁátˆùí¥Ñ•´¹™½ÉµÕ±…ôğ½Ñø(€€€€€€€€€€€€€€€€€€ñÑ±…ÍÍ9…µ”ô‰Áà´ÌÁä´ÈÑ•áĞµmÙ…È ´µ½±½ÈµµÕÑ•¥tˆùí¥Ñ•´¹É•…‘¥¹ôğ½Ñø(€€€€€€€€€€€€€€€€ğ½ÑÈø(€€€€€€€€€€€€€€¤¥ô(€€€€€€€€€€€€ğ½Ñ‰½‘äø(€€€€€€€€€€ğ½Ñ…‰±”ø(€€€€€€€€ğ½‘¥Øø(€€€€€€ğ½‘•Ñ…¥±Ìø(€€€€ğ¼ø(€€¤ì)ô(