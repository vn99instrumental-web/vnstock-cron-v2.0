// Version-agnostic (golden rule #2): đọc scoring_version/gate_version ĐỘNG từ run mới nhất.
// KHÔNG hardcode. Rỗng data → hiển thị "—".
import { createClient } from "@/lib/supabase/server";

export async function VersionBadge() {
  let sv = "—";
  let gv: string | number = "—";
  try {
    const supabase = await createClient();
    const { data } = await supabase
      .from("v4_runs")
      .select("scoring_version, gate_version, started_at")
      .order("started_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    sv = data?.scoring_version ?? "—";
    gv = data?.gate_version ?? "—";
  } catch {
    // Thiếu env / Supabase lỗi → hiển thị "—", không làm sập layout.
  }

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-0.5 text-[11px] text-[var(--color-muted)]"
      title="Phiên bản chấm điểm đọc động từ dữ liệu"
    >
      <span className="font-mono text-[var(--color-ink)]">scoring {sv}</span>
      <span aria-hidden>·</span>
      <span className="font-mono text-[var(--color-ink)]">gate {gv}</span>
    </span>
  );
}
