import { PageHeader, EmptyState } from "@/components/ui";
import { createClient } from "@/lib/supabase/server";
import { FACTOR_GROUPS, signalName } from "@/lib/interpret";
import { FactorVerMatrix, type FactorVerRow } from "@/components/factor-ver-matrix";
import { FactorICTable, type MargRow } from "@/components/factor-ic-table";

export const dynamic = "force-dynamic";

/** Ý nghĩa từng nhân tố (bám định nghĩa pipeline: FACTOR_GROUPS). */
const FACTOR_INFO: Record<string, { label: string; desc: string; members: string[] }> = {
  score_trade: {
    label: "Điểm tổng (score_trade)",
    desc: "Gộp tất cả các nhóm nhân tố thành 1 điểm cuối — chất lượng của tín hiệu MUA nói chung. IC hàng này = độ tin cậy của quyết định.",
    members: [],
  },
  ...Object.fromEntries(
    FACTOR_GROUPS.map((g) => [g.key, { label: g.label, desc: g.desc, members: g.members.map(signalName) }]),
  ),
};

/** Diễn giải độ mạnh + hướng của một ô IC (dùng cho tooltip). */
function icMeaning(ic: number | null): { strength: string; dir: string } {
  if (ic === null || !Number.isFinite(ic)) return { strength: "chưa có dữ liệu", dir: "" };
  const a = Math.abs(ic);
  const strength = a < 0.02 ? "gần như không dự báo" : a < 0.05 ? "có tín hiệu" : a < 0.1 ? "tốt" : "rất mạnh";
  const dir = ic > 0 ? "thuận (điểm cao ⇒ lời cao)" : ic < 0 ? "nghịch (điểm cao ⇒ lỗ)" : "trung tính";
  return { strength, dir };
}

// ── IC breakdown (chỉ số con / ngành) — ước lượng Spearman gộp, tham chiếu ──
interface BrkRow { key: string; horizon: number; ic: number | null; n: number }
type BrkGroup = { name: string; h: Map<number, { ic: number | null; n: number }> };

function groupBrk(rows: BrkRow[]): BrkGroup[] {
  const m = new Map<string, Map<number, { ic: number | null; n: number }>>();
  for (const r of rows) {
    if (!m.has(r.key)) m.set(r.key, new Map());
    m.get(r.key)!.set(r.horizon, { ic: r.ic, n: r.n });
  }
  const out: BrkGroup[] = [...m.entries()].map(([name, h]) => ({ name, h }));
  out.sort((a, b) => (b.h.get(5)?.ic ?? -99) - (a.h.get(5)?.ic ?? -99)); // mạnh nhất @5d lên đầu
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

/** Màu diverging: dương xanh lá, âm đỏ, đậm theo |IC| (chuẩn hoá ±0.2). */
function icCell(ic: number | null): { bg: string; fg: string } {
  if (ic === null || !Number.isFinite(ic)) return { bg: "transparent", fg: "var(--color-muted)" };
  const a = Math.min(1, Math.abs(ic) / 0.2) * 0.8;
  const bg = ic >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`;
  return { bg, fg: a > 0.45 ? "#fff" : "var(--color-ink)" };
}

/** Bảng heatmap breakdown: hàng = chỉ số/ngành (đã sort theo IC 5d), cột = horizon. */
function BreakdownTable({
  groups, colLabel, nameOf, minN = 30,
}: {
  groups: BrkGroup[];
  colLabel: string;
  nameOf: (k: string) => string;
  minN?: number;
}) {
  const rows = groups.filter((g) => (g.h.get(5)?.n ?? 0) >= minN);
  if (!rows.length) return <p className="text-xs text-[var(--color-muted)]">Chưa đủ dữ liệu.</p>;
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
                  ? `${nameOf(g.name)} · sau ${h} phiên\n` +
                    (ic === null ? "Chưa đủ dữ liệu" : `IC ${(ic >= 0 ? "+" : "") + ic.toFixed(3)} — ${m.strength}, ${m.dir}`) +
                    `\nn = ${c.n} quan sát (gộp mọi version)`
                  : "—";
                return (
                  <td key={h} className="tabular cursor-help px-3 py-2 text-center" style={{ backgroundColor: bg, color: fg }} title={title}>
                    {ic === null ? "—" : (ic >= 0 ? "+" : "") + ic.toFixed(3)}
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

  // Version production HIỆN TẠI (đọc động từ run mới nhất — version-agnostic).
  const { data: curRun } = await supabase
    .from("v4_runs")
    .select("scoring_version")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  const curVer = (curRun?.scoring_version as string | undefined) ?? null;
  const curHasIC = !!curVer && rows.some((r) => r.config_version === curVer);

  // IC breakdown (ước lượng Spearman gộp) — chỉ số con, ngành (gộp & theo version).
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

  // Chỉ số con GOM THEO FACTOR (mean_reversion gồm indicator nào…).
  const indByName = new Map(indGroups.map((g) => [g.name, g]));
  const indByFactor = FACTOR_GROUPS.map((fg) => ({
    key: fg.key,
    label: fg.label,
    members: fg.members.map((m) => indByName.get(m)).filter((g): g is BrkGroup => !!g),
  })).filter((f) => f.members.length);

  // IC theo ngành TÁCH THEO VERSION (chỉ version có ≥3 ngành đủ n).
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
        <PageHeader title="Chất lượng nhân tố (IC)" desc="Forward rank-IC theo factor × horizon." />
        <EmptyState
          title="Chưa có dữ liệu IC"
          hint="Chạy scripts/export_ic_to_supabase.py (evaluator Python, E6) sau khi có outcomes. Bảng v4_ic_metrics hiện rỗng."
        />
      </>
    );
  }

  // Danh sách version để render bảng hợp nhất: có IC official HOẶC có marginal.
  // Sort: version hiện tại lên đầu, rồi giảm dần theo số.
  const verList = [...new Set([
    ...rows.map((r) => r.config_version),
    ...marginalRows.map((r) => r.version),
  ])].sort(
    (a, b) => (b === curVer ? 1 : 0) - (a === curVer ? 1 : 0) || b.localeCompare(a, undefined, { numeric: true }),
  );

  return (
    <>
      <PageHeader
        title="Chất lượng nhân tố (IC)"
        desc="Forward rank-IC (Spearman theo ngày → trung bình). Tính bằng Python — nguồn chân lý. Xanh = dự báo thuận, đỏ = nghịch."
      />

      {curVer ? (
        <div className="card mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 p-2.5 text-[13px]">
          <span className="rounded-md bg-[var(--color-accent)] px-2 py-0.5 text-[11px] font-semibold text-white">HIỆN TẠI</span>
          <span className="font-mono font-semibold">scoring {curVer}</span>
          {curHasIC ? (
            <span className="text-[var(--color-muted)]">— IC bên dưới (đánh dấu &ldquo;hiện tại&rdquo;).</span>
          ) : (
            <span className="text-[var(--color-muted)]">
              — <b className="text-[var(--color-ink)]">chưa đủ dữ liệu forward để tính IC</b>. Mỗi lần đổi version là reset
              forward-validation → cần tích luỹ outcomes vài phiên rồi evaluator (Python) mới ghi IC. Bảng dưới là các
              version cũ đã đủ mẫu, dùng để tham chiếu.
            </span>
          )}
        </div>
      ) : null}

      <details open className="card mb-4 p-3 text-[13px]">
        <summary className="cursor-pointer select-none text-sm font-semibold">ℹ️ IC là gì &amp; đọc bảng thế nào?</summary>
        <div className="mt-2 flex flex-col gap-2 leading-relaxed text-[var(--color-muted)]">
          <p>
            <b className="text-[var(--color-ink)]">IC (Information Coefficient)</b> = tương quan hạng (Spearman) giữa
            điểm nhân tố lúc ra tín hiệu và <b className="text-[var(--color-ink)]">lợi nhuận thực tế sau N phiên</b>.
            Nói cách khác: điểm cao có <i>thật sự</i> đi kèm lời cao hơn không.
          </p>

          <div>
            <div className="mb-1 font-medium text-[var(--color-ink)]">Đọc độ mạnh |IC| (định lượng):</div>
            <ul className="grid gap-x-4 gap-y-0.5 sm:grid-cols-2">
              <li>≈ 0 → gần như không dự báo</li>
              <li>0.02 – 0.05 → có tín hiệu (đã đáng dùng)</li>
              <li>0.05 – 0.10 → tốt</li>
              <li>&gt; 0.10 → rất mạnh (hiếm — soi kỹ cỡ mẫu n kẻo overfit)</li>
            </ul>
          </div>

          <p>
            <b className="text-[var(--color-ink)]">Dấu &amp; màu:</b>{" "}
            <span className="font-semibold text-[var(--color-buy)]">+ xanh</span> = nhân tố cao ⇒ lời cao (dự báo
            thuận, đúng kỳ vọng);{" "}
            <span className="font-semibold text-[var(--color-sell)]">− đỏ</span> = nhân tố cao ⇒ lỗ (nghịch — factor
            đang phản tác dụng, nên cân nhắc giảm/đảo trọng số). Màu càng đậm ⇒ |IC| càng lớn (chuẩn hoá ±0.20).
          </p>

          <p>
            <b className="text-[var(--color-ink)]">Cột 1d/3d/5d/10d:</b> đo với lợi nhuận sau 1/3/5/10 phiên — một
            nhân tố có thể mạnh ở khung này nhưng yếu ở khung khác. So ngang để biết factor dự báo ngắn hay dài hạn.
          </p>

          <p>
            <b className="text-[var(--color-ink)]">Hàng:</b> <code>score_trade</code> = điểm tổng (chất lượng tín hiệu
            chung); các hàng còn lại = từng nhóm nhân tố.
          </p>

          <p>
            <b className="text-[var(--color-ink)]">n (rê chuột lên ô) = cỡ mẫu.</b> n nhỏ → IC nhiễu, chưa tin được.
            Ưu tiên ô có n lớn và qua nhiều phiên.
          </p>

          <p>
            <b className="text-[var(--color-ink)]">Nhóm theo version:</b> mỗi lần đổi SCORING_VERSION là reset
            forward-validation → IC tính riêng từng version. So version mới với cũ để biết thay đổi có cải thiện không.
          </p>

          <p className="italic">
            Lưu ý: đây là <b>forward IC</b> (đo trên tương lai thật, không phải backtest) — đáng tin hơn, nhưng vẫn cần
            đủ mẫu &amp; nhiều phiên mới kết luận. Con số chính thức do evaluator Python tính.
          </p>
        </div>
      </details>

      <details className="card mb-6 p-3 text-[13px]">
        <summary className="cursor-pointer select-none text-sm font-semibold">📖 Ý nghĩa từng nhân tố (rê chuột lên tên hàng / từng ô để xem nhanh)</summary>
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
                    <span className="font-medium">Chỉ báo thành viên:</span> {info.members.join(" · ")}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </details>

      <p className="mb-2 text-[12px] text-[var(--color-muted)]">
        Mỗi version: hàng <b>nhân tố</b> = IC chính thức (evaluator Python, chuẩn theo-ngày) × 1/3/5/10 phiên. Bấm nhân
        tố có dấu ▸ để <b>bung ra chỉ báo con</b> kèm <b>đóng góp biên</b> (hồi quy đa biến, khử trùng lặp) + cột
        <b> Kết luận</b> (GIỮ/tăng · GIẢM/đảo · trùng lặp) — dùng để combine version mới. Rê chuột ô để xem n / t-stat.
      </p>
      {verList.map((version) => (
        <FactorICTable
          key={version}
          version={version}
          curVer={curVer}
          official={rows.filter((r) => r.config_version === version)}
          marginal={marginalRows.filter((r) => r.version === version)}
        />
      ))}
      <p className="mb-6 text-xs text-[var(--color-muted)]">
        Ô nhân tố: độ đậm theo |IC| (±0.20). Ô chỉ báo (bung): độ đậm theo |hệ số biên| (±0.30), <b>in đậm = |t|≥2</b>
        (có ý nghĩa). IC official chỉ có ở version tích đủ ≥3 phiên chín; đóng góp biên có ở version đủ mẫu hồi quy (n≥150).
      </p>

      {/* ── Ma trận IC nhân tố × MỌI version (ước lượng) — công cụ combine ── */}
      <section className="mb-6">
        <h2 className="mb-1 text-sm font-semibold">🧮 So sánh nhân tố qua tất cả version — chọn yếu tố để combine</h2>
        <p className="mb-2 text-[12px] text-[var(--color-muted)]">
          Hàng = version, cột = nhân tố. Tìm nhân tố <b>dương ổn định qua nhiều version</b> (xanh nhiều cột) để tăng
          trọng số; nhân tố <b>đỏ dai dẳng</b> để giảm/đảo. Phủ hết mọi version (kể cả version cũ n nhỏ) —
          <b> ước lượng pooled</b>, tham chiếu; con số chuẩn xem bảng official phía trên.
        </p>
        <FactorVerMatrix rows={factorVerRows} curVer={curVer} minN={30} />
      </section>

      {/* ── IC theo CHỈ SỐ CON — gom theo nhóm nhân tố ── */}
      <section className="mb-6">
        <h2 className="mb-1 text-sm font-semibold">🔬 IC theo chỉ số con — gom theo nhóm nhân tố</h2>
        <p className="mb-2 text-[12px] text-[var(--color-muted)]">
          Mỗi nhóm nhân tố (mean_reversion, breakout…) gồm các <b>chỉ báo thành viên</b> bên dưới. IC = chỉ báo nào
          <b> dự báo tốt</b> (xanh) / <b>ngược</b> (đỏ). Ước lượng Spearman rank-IC gộp toàn kỳ (mọi version) — tham
          chiếu, không phải IC chính thức evaluator. Rê chuột xem n.
        </p>
        <div className="flex flex-col gap-3">
          {indByFactor.map((f) => (
            <div key={f.key}>
              <div className="mb-1 text-[13px] font-semibold">
                {f.label} <span className="font-mono text-[11px] font-normal text-[var(--color-muted)]">{f.key}</span>
              </div>
              <BreakdownTable groups={f.members} colLabel="Chỉ báo" nameOf={(k) => signalName(k)} minN={100} />
            </div>
          ))}
        </div>
      </section>


      {/* ── IC theo NGÀNH (gộp + per-version) ── */}
      <section className="mb-4">
        <h2 className="mb-1 text-sm font-semibold">🏭 IC theo ngành — điểm số hiệu quả ở ngành nào?</h2>
        <p className="mb-2 text-[12px] text-[var(--color-muted)]">
          Spearman rank-IC gộp giữa <code>score_trade</code> và lợi nhuận sau N phiên, tách theo ngành, <b>riêng từng
          version</b> (điểm mô hình đáng tin ở ngành nào — xanh, ngược ở ngành nào — đỏ). Ước lượng tham chiếu.
        </p>

        {indusByVer.length ? (
          <div>
            {indusByVer.map((v) => (
              <details key={v.version} className="mb-1.5 rounded-md border border-[var(--color-border)] p-2" open={v.version === curVer}>
                <summary className="cursor-pointer select-none font-mono text-[13px] font-semibold">
                  scoring {v.version}{v.version === curVer ? " (hiện tại)" : ""}
                </summary>
                <div className="mt-1.5">
                  <BreakdownTable groups={v.groups} colLabel="Ngành" nameOf={(k) => k} minN={30} />
                </div>
              </details>
            ))}
          </div>
        ) : null}
      </section>
    </>
  );
}
