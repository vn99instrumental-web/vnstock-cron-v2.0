import { PageHeader, EmptyState } from "@/components/ui";

export default async function SignalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <PageHeader
        title="Chi tiết tín hiệu"
        desc={`Drill-down 1 tín hiệu (id: ${id}).`}
      />
      <EmptyState
        title="Chưa có dữ liệu"
        hint="Breakdown (factor s_*, gates, ranks, shadow decisions, outcome ret_*) sẽ dựng ở E3. Lưu ý escape khi render breakdown jsonb (note security-review E1)."
      />
    </>
  );
}
