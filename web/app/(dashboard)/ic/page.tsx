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
    desc: "Gộp tất cả các nhóm nhân tố thành một điểm cuối — chất lượng của tín hiệu MUA nói chung. IC hàng này thể hiện độ tin cậy của quyết định.",
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
  const dir = ic > 0 ? "thuận (Điểm cao ⇒ lời cao)" : ic < 0 ? "nghịch (Điểm cao ⇒ lỗ)" : "trung tính";
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
  groups, colLabel, nameOf, minN = 30, showSample = false,
}: {
  groups: BrkGroup[];
  colLabel: string;
  nameOf: (k: string) => string;
  minN?: number;
  showSample?: boolean;
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
                  <td key={h} className="tabular min-w-[76px] cursor-help px-3 py-2 text-center" style={{ backgroundColor: bg, color: fg }} title={title}>
                    <div>{ic === null ? "—" : (ic >= 0 ? "+" : "") + ic.toFixed(3)}</div>
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
  const industryError = indusVerRes.error;
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

  // IC theo ngành TÁCH THEO VERSION; hiển thị n để người dùng tự đánh giá độ tin cậy.
  const verMap = new Map<string, BrkRow[]>();
  for (const r of (indusVerRes.data ?? []) as Record<string, unknown>[]) {
    const v = String(r.version);
    if (!verMap.has(v)) verMap.set(v, []);
    verMap.get(v)!.push({ key: String(r.industry), horizon: Number(r.horizon), ic: r.ic == null ? null : Number(r.ic), n: Number(r.n) });
  }
  const indusByVer = [...verMap.entries()]
    .map(([version, rws]) => ({ version, groups: groupBrk(rws) }))
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

  const sampleByVersion = verList.map((version) => {
    const byHorizon = new Map<number, number>();
    for (const r of rows) if (r.config_version === version && r.n != null) byHorizon.set(r.horizon, Math.max(byHorizon.get(r.horizon) ?? 0, Number(r.n)));
    return { version, byHorizon };
  });

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
      {verList.map((version) => (
        <FactorICTable
          key={version}
          version={version}
          curVer={curVer}
          official={rows.filter((r) => r.config_version === version)}
          marginal={marginalRows.filter((r) => r.version === version)}
        />
      ))}
      {/* IC theo ngành: version hiện tại mở sẵn, version cũ thu gọn. */}
      <section className="card mb-6 p-3 sm:p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">IC theo ngành</h2>
            <p className="mt-1 text-[12px] text-[var(--color-muted)]">
              Khả năng dự báo của <code>score_trade</code> theo từng ngành và từng scoring version. Xanh = thuận, đỏ = nghịch.
            </p>
          </div>
          <span className="rounded-md border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-muted)]">
            IC Spearman · n = cỡ mẫu
          </span>
        </div>

        {indusByVer.length ? (
          <div className="space-y-2">
            {indusByVer.map((v, index) => (
              <details
                key={v.version}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5"
                open={v.version === curVer || (!curVer && index === 0)}
              >
                <summary className="flex cursor-pointer select-none items-center justify-between gap-2 font-mono text-[13px] font-semibold">
                  <span>scoring {v.version}{v.version === curVer ? " (hiện tại)" : ""}</span>
                  <span className="font-sans text-[11px] font-normal text-[var(--color-muted)]">{v.groups.length} ngành</span>
                </summary>
                <div className="mt-2">
                  <BreakdownTable groups={v.groups} colLabel="Ngành" nameOf={(k) => k} minN={1} showSample />
                  <p className="mt-1.5 text-[11px] text-[var(--color-muted)]">
                    Thận trọng với ô có n &lt; 30; cỡ mẫu nhỏ khiến IC dễ biến động.
                  </p>
                </div>
              </details>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-[var(--color-border)] px-3 py-6 text-center text-xs text-[var(--color-muted)]">
            {industryError ? "Không tải được IC theo ngành từ Supabase. Vui lòng tải lại trang." : "Chưa có dữ liệu IC theo ngành trong phiên bản đang chọn."}
          </div>
        )}
      </section>
      <details className="card mb-4 p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold">Cách đọc bảng IC</summary>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="bg-black/[0.03] text-[var(--color-muted)] dark:bg-white/[0.03]"><tr><th className="px-3 py-2 text-left">Khái niệm</th><th className="px-3 py-2 text-left">Cách hiểu</th></tr></thead>
            <tbody>
              <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">IC</td><td className="px-3 py-2 text-[var(--color-muted)]">Tương quan hạng Spearman giữa điểm nhân tố khi phát tín hiệu và lợi nhuận thực tế sau N phiên.</td></tr>
              <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Độ mạnh |IC|</td><td className="px-3 py-2 text-[var(--color-muted)]">Dưới 0,02: gần như không dự báo; 0,02–0,05: có tín hiệu; 0,05–0,10: tốt; trên 0,10: rất mạnh và cần kiểm tra cỡ mẫu.</td></tr>
              <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Dấu và màu</td><td className="px-3 py-2 text-[var(--color-muted)]"><span className="font-semibold text-[var(--color-buy)]">Dương, màu xanh</span>: dự báo thuận. <span className="font-semibold text-[var(--color-sell)]">Âm, màu đỏ</span>: dự báo nghịch. Màu đậm hơn nghĩa là |IC| lớn hơn.</td></tr>
              <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">1d / 3d / 5d / 10d</td><td className="px-3 py-2 text-[var(--color-muted)]">Lợi nhuận được đo sau 1, 3, 5 hoặc 10 phiên để phân biệt khả năng dự báo ngắn và dài hạn.</td></tr>
              <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Cỡ mẫu n</td><td className="px-3 py-2 text-[var(--color-muted)]">n nhỏ làm IC dễ nhiễu. Ưu tiên kết quả có n lớn và ổn định qua nhiều khung phiên.</td></tr>
              <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Scoring version</td><td className="px-3 py-2 text-[var(--color-muted)]">Mỗi version được forward-validation riêng. Khi đổi version, cần tích lũy outcomes mới trước khi kết luận.</td></tr>
              <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Nguồn số liệu</td><td className="px-3 py-2 text-[var(--color-muted)]">IC chính thức do evaluator Python tính trên dữ liệu tương lai thực, không phải backtest.</td></tr>
            </tbody>
          </table>
        </div>
      </details>

      <details className="card mb-4 p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold">Ý nghĩa từng nhân tố</summary>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="bg-black/[0.03] text-[var(--color-muted)] dark:bg-white/[0.03]"><tr><th className="px-3 py-2 text-left">Mã nhân tố</th><th className="px-3 py-2 text-left">Tên</th><th className="px-3 py-2 text-left">Diễn giải</th><th className="px-3 py-2 text-left">Chỉ báo thành viên</th></tr></thead>
            <tbody>{FACTOR_ORDER.filter((key) => FACTOR_INFO[key]).map((key) => { const info = FACTOR_INFO[key]; return (
              <tr key={key} className="border-t border-[var(--color-border)] align-top"><td className="px-3 py-2 font-mono font-semibold">{key}</td><td className="px-3 py-2 font-medium">{info.label}</td><td className="px-3 py-2 text-[var(--color-muted)]">{info.desc}</td><td className="px-3 py-2 text-[var(--color-muted)]">{info.members.length ? info.members.join(" · ") : "—"}</td></tr>
            ); })}</tbody>
          </table>
        </div>
      </details>

      <details className="card mb-4 p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold">So sánh nhân tố qua tất cả version</summary>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--color-border)]"><table className="w-full min-w-[640px] text-xs"><thead className="bg-black/[0.03] text-[var(--color-muted)] dark:bg-white/[0.03]"><tr><th className="px-3 py-2 text-left">Nội dung</th><th className="px-3 py-2 text-left">Cách sử dụng</th></tr></thead><tbody>
          <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Mục đích</td><td className="px-3 py-2 text-[var(--color-muted)]">Tìm nhân tố dương ổn định qua nhiều version để cân nhắc tăng trọng số; nhân tố âm dai dẳng để cân nhắc giảm hoặc đảo trọng số.</td></tr>
          <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Phạm vi</td><td className="px-3 py-2 text-[var(--color-muted)]">Ước lượng pooled trên các version có đủ mẫu; dùng để tham chiếu. Số chính thức nằm ở bảng scoring phía trên.</td></tr>
        </tbody></table></div>
        <div className="mt-3"><FactorVerMatrix rows={factorVerRows} curVer={curVer} minN={30} /></div>
      </details>

      <details className="card mb-4 p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold">IC theo chỉ số con</summary>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--color-border)]"><table className="w-full min-w-[640px] text-xs"><thead className="bg-black/[0.03] text-[var(--color-muted)] dark:bg-white/[0.03]"><tr><th className="px-3 py-2 text-left">Nội dung</th><th className="px-3 py-2 text-left">Cách đọc</th></tr></thead><tbody>
          <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Nhóm dữ liệu</td><td className="px-3 py-2 text-[var(--color-muted)]">Các chỉ báo thành viên được gom theo nhóm nhân tố như mean_reversion, breakout, flow và các nhóm còn lại.</td></tr>
          <tr className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-medium">Ý nghĩa</td><td className="px-3 py-2 text-[var(--color-muted)]">Xanh là chỉ báo dự báo thuận, đỏ là dự báo nghịch. Đây là ước lượng Spearman pooled toàn kỳ để tham chiếu; rê chuột lên ô để xem n.</td></tr>
        </tbody></table></div>
        <div className="mt-3 flex flex-col gap-3">{indByFactor.map((factor) => (
          <div key={factor.key}><div className="mb-1 text-[13px] font-semibold">{factor.label} <span className="font-mono text-[11px] font-normal text-[var(--color-muted)]">{factor.key}</span></div><BreakdownTable groups={factor.members} colLabel="Chỉ báo" nameOf={(key) => signalName(key)} minN={100} /></div>
        ))}</div>
      </details>

      <details className="card mb-6 p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold">Số lượng mẫu theo scoring version</summary>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--color-border)]"><table className="w-full text-xs"><thead className="bg-black/[0.03] text-[var(--color-muted)] dark:bg-white/[0.03]"><tr><th className="px-3 py-2 text-left">Version</th>{HORIZONS.map((h) => <th key={h} className="px-3 py-2 text-right">{h} phiên</th>)}</tr></thead><tbody>{sampleByVersion.map(({ version, byHorizon }) => <tr key={version} className="border-t border-[var(--color-border)]"><td className="px-3 py-2 font-mono">{version}{version === curVer ? " (hiện tại)" : ""}</td>{HORIZONS.map((h) => <td key={h} className="tabular px-3 py-2 text-right">{byHorizon.get(h)?.toLocaleString() ?? "—"}</td>)}</tr>)}</tbody></table></div>
      </details>
    </>
  );
}
