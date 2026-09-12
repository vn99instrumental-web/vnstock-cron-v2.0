import { redirect } from "next/navigation";
import { PageHeader, EmptyState } from "@/components/ui";
import { getUser, isOwner } from "@/lib/supabase/server";

export default async function ConfigPage() {
  // Defense-in-depth: middleware đã chặn, kiểm lại server-side (ADR-007).
  const user = await getUser();
  if (!isOwner(user?.email)) redirect("/login?next=/config");

  return (
    <>
      <PageHeader
        title="Cấu hình chấm điểm"
        desc="Đề xuất weights / gates / thresholds → shadow → promote (E4). Chỉ owner."
      />
      <EmptyState
        title="Editor sẽ được dựng ở E4"
        hint="Bao gồm: editor 4 nhóm config (factor_weights, gate_matrix, thresholds, extras), simulate.ts (nhãn simulation), và Promote server-only ghi active.json. Shadow ≥30 phiên trước promote."
      />
    </>
  );
}
