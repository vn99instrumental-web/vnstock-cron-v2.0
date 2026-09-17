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
