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
const TECHNICAL_TERMS = [
  { term: "Spearman (ρ)", meaning: "Đo mức độ hai biến tăng hoặc giảm cùng thứ tự, không yêu cầu quan hệ tuyến tính.", formula: "ρ = 1 − 6Σd² / [n(n²−1)] (khi không có hạng trùng)", reading: "+1: cùng chiều hoàn toàn; 0: không có quan hệ hạng; −1: ngược chiều hoàn toàn." },
  { term: "IC (Information Coefficient)", meaning: "Spearman giữa điểm tín hiệu hôm nay và lợi nhuận tương lai; đo khả năng xếp hạng cổ phiếu.", formula: "IC = Spearman(score, future return)", reading: "|IC| < 0,02: yếu; 0,02–0,05: có tín hiệu; 0,05–0,10: tốt; > 0,10: mạnh. IC âm là dự báo ngược." },
  { term: "Williams %R", meaning: "Cho biết giá đóng cửa đang nằm gần đỉnh hay đáy của biên giá N phiên.", formula: "%R = −100 × (HighN − Close) / (HighN − LowN)", reading: "Từ −100 đến 0. Dưới −80: quá bán; trên −20: quá mua. Không nên dùng riêng lẻ làm lệnh mua/bán." },
  { term: "Bollinger Bands / %B", meaning: "Đo vị trí giá so với dải biến động quanh trung bình động.", formula: "%B = (Price − Lower Band) / (Upper Band − Lower Band)", reading: "%B < 0: dưới dải dưới; 0–1: trong dải; > 1: trên dải trên. Cần kết hợp xu hướng và khối lượng." },
  { term: "EMA", meaning: "Trung bình động đặt trọng số lớn hơn cho giá gần hiện tại.", formula: "EMAₜ = αPriceₜ + (1−α)EMAₜ₋₁; α = 2/(N+1)", reading: "Giá trên EMA thường thiên tăng; dưới EMA thường thiên giảm. Khoảng cách quá xa có thể báo trạng thái quá căng." },
  { term: "Relative Strength (RS)", meaning: "So sánh hiệu suất của một mã với chỉ số tham chiếu trong cùng giai đoạn.", formula: "RS = (1 + return mã) / (1 + return chỉ số)", reading: "> 1: mã mạnh hơn thị trường; < 1: yếu hơn. RS tăng đều đáng tin hơn một điểm tăng đơn lẻ." },
  { term: "Breakout", meaning: "Giá vượt vùng cản hoặc đỉnh trước, thường dùng để nhận biết xu hướng mới.", formula: "Price > resistance; xác nhận thường kèm Volume / Volume MA > 1", reading: "Tốt hơn khi đóng cửa trên cản và khối lượng tăng. Vượt cản rồi quay xuống nhanh có thể là breakout giả." },
  { term: "Order flow", meaning: "Chênh lệch tương đối giữa khối lượng mua chủ động và bán chủ động.", formula: "OF ≈ (Buy active − Sell active) / (Buy active + Sell active)", reading: "> 0: áp lực mua; < 0: áp lực bán; gần 0: cân bằng. Cách phân loại lệnh phụ thuộc nguồn dữ liệu." },
  { term: "t-stat", meaning: "Đo hệ số ước lượng lớn bao nhiêu so với sai số của chính nó.", formula: "t = coefficient / standard error", reading: "Quy ước |t| ≥ 2: có ý nghĩa thống kê tương đối; |t| nhỏ: chưa đủ bằng chứng. Không đồng nghĩa chắc chắn có lãi." },
  { term: "R²", meaning: "Tỷ lệ biến động của lợi nhuận được mô hình giải thích trên mẫu đã dùng.", formula: "R² = 1 − SSE/SST", reading: "Từ 0 đến 1; cao hơn là khớp mẫu tốt hơn, nhưng quá cao trên mẫu nhỏ có thể là overfit." },
  { term: "Horizon", meaning: "Số phiên từ ngày phát tín hiệu đến ngày đo lợi nhuận.", formula: "ReturnNh = Price(t+N) / Price(t) − 1", reading: "1d/3d phản ánh rất ngắn hạn; 5d/10d phản ánh độ bền dài hơn của tín hiệu." },
  { term: "n (cỡ mẫu)", meaning: "Số quan sát hợp lệ dùng để tính chỉ số.", formula: "n = số cặp (score, future return) hợp lệ", reading: "n càng lớn thường càng ổn định. Với bảng ngành, n < 30 nên xem là tham khảo thận trọng." },
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
  const officialVersions = [...new Set(rows.map((r) => r.config_version))].sort(
    (a, b) => (b === curVer ? 1 : 0) - (a === curVer ? 1 : 0) || b.localeCompare(a, undefined, { numeric: true }),
  );

  // IC breakdown: chỉ số con và IC ngành tách theo version × category.
  // Mỗi version là một request riêng để không chạm giới hạn 1.000 dòng của PostgREST.
  const [indRes, factorVerRes, margRes, industryBatchRes] = await Promise.all([
    supabase.from("v4_ic_by_indicator").select("indicator, horizon, ic, n"),
    supabase.from("v4_ic_by_factor_ver").select("version, factor, horizon, ic, n"),
    supabase.from("v4_marginal_ic").select("version, indicator, factor, horizon, coef, tstat, univar_ic, n"),
    supabase.from("v4_ic_industry_batch").select("batch_id, data_asof, computed_at").eq("status", "ready").order("computed_at", { ascending: false }).limit(1).maybeSingle(),
  ]);
  const { data: industryData } = industryBatchRes.data ? await supabase.from("v4_ic_industry_metrics").select("version, factor, industry, horizon, ic, n").eq("batch_id", industryBatchRes.data.batch_id).order("factor", { ascending: true }).order("industry", { ascending: true }).order("horizon", { ascending: true }) : { data: [] };
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

  const industryByVersion = officialVersions.map((version) => ({
    version,
    error: industryBatchRes.error?.message ?? null,
    factors: FACTOR_ORDER.map((factor) => ({
      factor,
      groups: groupBrk(toBrk(
        ((industryData ?? []) as Record<string, unknown>[]).filter((row) => row.version === version && row.factor === factor),
        "industry",
      )),
    })).filter((item) => item.groups.length),
  }));

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

  // Chỉ hiện version có IC official; version chỉ có marginal không tạo bảng rỗng.
  const verList = officialVersions;

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
      {verList.filter((version) => version === curVer).map((version) => (
        <FactorICTable
          key={version}
          version={version}
          curVer={curVer}
          official={rows.filter((r) => r.config_version === version)}
          marginal={marginalRows.filter((r) => r.version === version)}
        />
      ))}

      {verList.filter((version) => version !== curVer).map((version) => (
        <FactorICTable
          key={version}
          version={version}
          curVer={curVer}
          official={rows.filter((r) => r.config_version === version)}
          marginal={marginalRows.filter((r) => r.version === version)}
        />
      ))}
      <section className="card mb-6 p-3 sm:p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">IC theo ngành và nhóm scoring</h2>
            <p className="mt-1 text-[12px] text-[var(--color-muted)]">
              Mỗi scoring version được tách theo điểm tổng và 6 category. Mở version, sau đó mở category cần xem.
            </p>
          </div>
          <span className="rounded-md border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-muted)]">
            IC Spearman · n = cỡ mẫu
          </span>
        </div>

        {officialVersions.length ? (
          <div className="space-y-2">
            {industryByVersion.map((versionData) => (
              <details
                key={versionData.version}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5"
                open={versionData.version === curVer}
              >
                <summary className="flex cursor-pointer select-none items-center justify-between gap-2 font-mono text-[13px] font-semibold">
                  <span>scoring {versionData.version}{versionData.version === curVer ? " (hiện tại)" : ""}</span>
                  <span className="font-sans text-[11px] font-normal text-[var(--color-muted)]">{versionData.factors.length} category</span>
                </summary>
                <div className="mt-2 space-y-2">
                  {versionData.error ? (
                    <div className="rounded-md border border-dashed border-[var(--color-border)] px-3 py-4 text-center text-xs text-[var(--color-muted)]">
                      Không tải được dữ liệu của scoring {versionData.version}. Vui lòng tải lại trang.
                    </div>
                  ) : versionData.factors.map((factorData) => {
                    const info = FACTOR_INFO[factorData.factor];
                    return (
                      <details
                        key={factorData.factor}
                        className="rounded-md border border-[var(--color-border)] bg-black/[0.015] p-2 dark:bg-white/[0.02]"
                        open={factorData.factor === "score_trade"}
                      >
                        <summary className="flex cursor-pointer select-none items-center justify-between gap-2 text-[12px] font-semibold">
                          <span>{info?.label ?? factorData.factor}</span>
                          <span className="font-normal text-[var(--color-muted)]">{factorData.groups.length} ngành</span>
                        </summary>
                        <div className="mt-2">
                          <BreakdownTable groups={factorData.groups} colLabel="Ngành" nameOf={(key) => key} minN={1} showSample />
                        </div>
                      </details>
                    );
                  })}
                  <p className="text-[11px] text-[var(--color-muted)]">
                    Đây là IC pooled để so tương đối giữa ngành/category. Thận trọng với ô có n &lt; 30; IC official theo ngày vẫn nằm ở bảng scoring phía trên.
                  </p>
                </div>
              </details>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-[var(--color-border)] px-3 py-6 text-center text-xs text-[var(--color-muted)]">
            Chưa có IC theo ngành cho các scoring version có IC official.
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
      <details className="card mb-6 p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold">Thuật ngữ chuyên môn và cách đọc</summary>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full min-w-[980px] text-xs">
            <thead className="bg-black/[0.03] text-[var(--color-muted)] dark:bg-white/[0.03]">
              <tr>
                <th className="px-3 py-2 text-left">Thuật ngữ</th>
                <th className="px-3 py-2 text-left">Định nghĩa dễ hiểu</th>
                <th className="px-3 py-2 text-left">Công thức cơ bản</th>
                <th className="px-3 py-2 text-left">Cách đọc / tốt / xấu</th>
              </tr>
            </thead>
            <tbody>
              {TECHNICAL_TERMS.map((item) => (
                <tr key={item.term} className="border-t border-[var(--color-border)] align-top">
                  <td className="px-3 py-2 font-semibold">{item.term}</td>
                  <td className="px-3 py-2 text-[var(--color-muted)]">{item.meaning}</td>
                  <td className="px-3 py-2 font-mono text-[11px]">{item.formula}</td>
                  <td className="px-3 py-2 text-[var(--color-muted)]">{item.reading}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
