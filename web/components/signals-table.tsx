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

/** Bảng tín hiệu: bảng data-dense trên desktop, card xếp chồng dễ chạm trên mobile. */
export function SignalsTable({
  rows,
  showDate = false,
}: {
  rows: SignalRow[];
  showDate?: boolean;
}) {
  return (
    <>
      {/* MOBILE: card list (tap → chi tiết) */}
      <ul className="flex flex-col gap-1.5 md:hidden">
        {rows.map((r) => {
          const b = r.breakdown ?? {};
          return (
            <li key={r.id}>
              <Link href={`/history/${r.id}`} className="card flex items-center gap-2 px-3 py-2.5 active:bg-black/[0.03] dark:active:bg-white/[0.03]">
                <span className="w-14 shrink-0 font-semibold">{r.symbol}</span>
                <DecisionBadge decision={r.decision} />
                <span className="tabular ml-auto shrink-0 text-right font-semibold">{fmtNum(r.score_trade)}</span>
                <span className="tabular w-16 shrink-0 text-right text-[13px] text-[var(--color-muted)]">{fmtNum(b.price)}</span>
              </Link>
              <div className="mt-0.5 px-3 text-[10px] text-[var(--color-muted)]">
                {showDate ? <>{r.signal_date} · {snapHM(r.snap_time)} · </> : null}
                {r.regime ?? "—"} · conf {String(b.confidence ?? "—")}
              </div>
            </li>
          );
        })}
      </ul>

      {/* DESKTOP: bảng */}
      <div className="hidden overflow-x-auto rounded-lg border border-[var(--color-border)] md:block">
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
                  <td className="px-3 py-2"><DecisionBadge decision={r.decision} /></td>
                  <td className="tabular px-3 py-2 text-right">{fmtNum(r.score_trade)}</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-muted)]">{r.regime ?? "—"}</td>
                  <td className="px-3 py-2 text-xs">{String(b.confidence ?? "—")}</td>
                  <td className="tabular px-3 py-2 text-right">{fmtNum(b.price)}</td>
                  {showDate ? (
                    <td className="px-3 py-2 text-xs text-[var(--color-muted)]">
                      {r.signal_date} · {snapHM(r.snap_time)}
                    </td>
                  ) : null}
                  <td className="px-2 py-1.5 text-right">
                    <Link
                      href={`/history/${r.id}`}
                      className="inline-flex min-h-[36px] items-center rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--color-accent)] active:bg-[var(--color-accent)]/10 hover:underline"
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
    </>
  );
}
