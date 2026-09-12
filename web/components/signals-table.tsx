import Link from "next/link";
import { DecisionBadge } from "@/components/ui";
import { fmtNum, snapHM } from "@/lib/format";

export interface SignalRow {
  id: number;
  symbol: string;
  decision: string | null;
  score_trade: number | null;
  regime: string | null;
  signal_date: string;
  snap_time: string | null;
  scoring_version: string | null;
  breakdown: Record<string, unknown> | null;
}

/** Bảng tín hiệu data-dense. Dùng cho Today + History. */
export function SignalsTable({
  rows,
  showDate = false,
}: {
  rows: SignalRow[];
  showDate?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full text-sm">
        <thead className="bg-black/[0.03] text-left text-xs text-[var(--color-muted)] dark:bg-white/[0.03]">
          <tr>
            <th className="px-3 py-2">Mã</th>
            <th className="px-3 py-2">Quyết định</th>
            <th className="px-3 py-2 text-right">Score</th>
            <th className="px-3 py-2">Regime</th>
            <th className="px-3 py-2">Confidence</th>
            <th className="px-3 py-2 text-right">Giá</th>
            {showDate ? <th className="px-3 py-2">Ngày · snap</th> : null}
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const b = r.breakdown ?? {};
            return (
              <tr
                key={r.id}
                className="border-t border-[var(--color-border)] hover:bg-black/[0.02] dark:hover:bg-white/[0.02]"
              >
                <td className="px-3 py-2 font-semibold">{r.symbol}</td>
                <td className="px-3 py-2">
                  <DecisionBadge decision={r.decision} />
                </td>
                <td className="tabular px-3 py-2 text-right">{fmtNum(r.score_trade)}</td>
                <td className="px-3 py-2 text-xs text-[var(--color-muted)]">{r.regime ?? "—"}</td>
                <td className="px-3 py-2 text-xs">{String(b.confidence ?? "—")}</td>
                <td className="tabular px-3 py-2 text-right">{fmtNum(b.price)}</td>
                {showDate ? (
                  <td className="px-3 py-2 text-xs text-[var(--color-muted)]">
                    {r.signal_date} · {snapHM(r.snap_time)}
                  </td>
                ) : null}
                <td className="px-3 py-2 text-right">
                  <Link
                    href={`/history/${r.id}`}
                    className="text-xs text-[var(--color-accent)] hover:underline"
                  >
                    chi tiết →
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
