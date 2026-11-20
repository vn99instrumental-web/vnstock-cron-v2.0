import type { GroupMemberView } from "@/lib/interpret";
import { DIR_COLOR } from "@/lib/interpret";

export function FactorMemberEvidence({ member }: { member: GroupMemberView }) {
  if (!member.details?.length && !member.method) return null;

  return (
    <div className="ml-[3.25rem] mt-1.5 rounded border border-[var(--color-border)]/70 bg-black/[0.018] px-2 py-1.5 dark:bg-white/[0.025]">
      {member.details?.length ? (
        <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
          {member.details.map((detail) => (
            <div key={detail.label} className="flex min-w-0 items-baseline justify-between gap-2 text-[10px] leading-tight">
              <dt className="truncate text-[var(--color-muted)]">{detail.label}</dt>
              <dd className="flex shrink-0 items-baseline gap-1.5">
                <span className="font-medium" style={{ color: DIR_COLOR[detail.dir] }}>{detail.signal}</span>
                <span className="tabular font-semibold text-[var(--color-ink)]">{detail.value}</span>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {member.evidenceNote ? (
        <p className="mt-1 text-[10px] leading-tight text-[var(--color-muted)]">
          {member.evidenceNote}
        </p>
      ) : null}
      {member.method ? (
        <p className="mt-1 border-t border-[var(--color-border)]/60 pt-1 text-[10px] leading-tight text-[var(--color-muted)]">
          <span className="font-medium text-[var(--color-ink)]">Phép tính:</span> {member.method}
        </p>
      ) : null}
    </div>
  );
}
