import { PageHeader, EmptyState } from "@/components/ui";

export default function ICPage() {
  return (
    <>
      <PageHeader
        title="Chất lượng nhân tố (IC)"
        desc="Forward rank-IC theo factor × horizon (tính bằng Python, nguồn chân lý)."
      />
      <EmptyState
        title="Chưa có dữ liệu IC"
        hint="Bảng v4_ic_metrics sẽ được ghi bởi evaluator Python (E6). Heatmap/bảng IC dựng sau đó."
      />
    </>
  );
}
