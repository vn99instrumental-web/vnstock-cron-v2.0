// Version-agnostic (golden rule #2): đọc scoring_version/gate_version ĐỘNG từ run mới nhất.
// KHÔNG hardcode. Rỗng data → hiển thị "—".
import { createClient } from "@/lib/supabase/server";

export async function VersionBadge() {
  const supabase = await createClient();
  const { data } = await supabase
    .from("v4_runs")
    .select("scoring_version, gate_version, started_at")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const sv = data?.scoring_version ?? "—";
  const gv = data?.gate_version ?? "—";

  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs text-[var(--color-muted)]"
      title="Phiên bản chấm điểm đọc động từ dữ liệu"
    >
      <span className="font-mono text-[var(--color-ink)]">scoring {sv}</span>
      <span aria-hidden>·</span>
      <span className="font-mono text-[var(--color-ink)]">gate {gv}</span>
    </span>
  );
}
