import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui";
import { ConfigEditor } from "@/components/config-editor";
import { createClient, getUser, isOwner } from "@/lib/supabase/server";
import { DEFAULT_CONFIG } from "@/lib/scoring/default-config";
import type { ScoringConfig } from "@/lib/scoring/simulate";

export default async function ConfigPage() {
  // Defense-in-depth: middleware đã chặn, kiểm lại server-side (ADR-007).
  const user = await getUser();
  if (!isOwner(user?.email)) redirect("/login?next=/config");

  // Load config production hiện tại (nếu có), else baseline.
  const supabase = await createClient();
  const { data } = await supabase
    .from("v4_scoring_configs")
    .select("version_label, status, factor_weights, gate_matrix, thresholds, extras_cfg")
    .eq("status", "production")
    .order("promoted_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const initial: ScoringConfig = data
    ? {
        version_label: data.version_label,
        status: data.status,
        factor_weights: data.factor_weights,
        gate_matrix: data.gate_matrix,
        thresholds: data.thresholds,
        extras: data.extras_cfg ?? undefined,
      }
    : DEFAULT_CONFIG;

  return (
    <>
      <PageHeader
        title="Cấu hình chấm điểm"
        desc="Đề xuất weights / gates / thresholds → mô phỏng → promote. One-change-per-cycle · shadow-first."
      />
      <ConfigEditor initialConfig={initial} />
    </>
  );
}
