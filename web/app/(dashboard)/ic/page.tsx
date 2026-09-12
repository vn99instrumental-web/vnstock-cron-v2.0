import { PageHeader, EmptyState } from "@/components/ui";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

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

export default async function ICPage() {
  const supabase = await createClient();
  const { data } = await supabase
    .from("v4_ic_metrics")
    .select("config_version, factor, horizon, ic, n")
    .order("config_version", { ascending: false })
    .order("factor", { ascending: true })
    .order("horizon", { ascending: true });

  const rows = (data ?? []) as ICRow[];

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

  // group theo version → factor → horizon → ic
  const byVer = new Map<string, Map<string, Map<number, ICRow>>>();
  for (const r of rows) {
    if (!byVer.has(r.config_version)) byVer.set(r.config_version, new Map());
    const fm = byVer.get(r.config_version)!;
    if (!fm.has(r.factor)) fm.set(r.factor, new Map());
    fm.get(r.factor)!.set(r.horizon, r);
  }

  return (
    <>
      <PageHeader
        title="Chất lượng nhân tố (IC)"
        desc="Forward rank-IC (Spearman theo ngày → trung bình). Tính bằng Python — nguồn chân lý. Xanh = dự báo thuận, đỏ = nghịch."
      />
      {[...byVer.entries()].map(([version, fm]) => {
        const factors = FACTOR_ORDER.filter((f) => fm.has(f)).concat(
          [...fm.keys()].filter((f) => !FACTOR_ORDER.includes(f)),
        );
        return (
          <div key={version} className="mb-6">
            <h2 className="mb-2 font-mono text-sm font-semibold">scoring {version}</h2>
            <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
              <table className="w-full text-sm">
                <thead className="bg-black/[0.03] text-xs text-[var(--color-muted)] dark:bg-white/[0.03]">
                  <tr>
                    <th className="px-3 py-2 text-left">Factor</th>
                    {HORIZONS.map((h) => (
                      <th key={h} className="px-3 py-2 text-center">{h}d</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {factors.map((f) => (
                    <tr key={f} className="border-t border-[var(--color-border)]">
                      <td className="px-3 py-2 font-medium">{f}</td>
                      {HORIZONS.map((h) => {
                        const r = fm.get(f)?.get(h);
                        const ic = r?.ic ?? null;
                        const { bg, fg } = icCell(ic);
                        return (
                          <td
                            key={h}
                            className="tabular px-3 py-2 text-center"
                            style={{ backgroundColor: bg, color: fg }}
                            title={r ? `n=${r.n}` : "—"}
                          >
                            {ic === null ? "—" : (ic >= 0 ? "+" : "") + ic.toFixed(3)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
      <p className="text-xs text-[var(--color-muted)]">
        Độ đậm màu theo |IC| (chuẩn hoá ±0.20). Hover ô để xem cỡ mẫu n.
      </p>
    </>
  );
}
