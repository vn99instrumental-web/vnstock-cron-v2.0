import { PageHeader, EmptyState } from "@/components/ui";

export default function HistoryPage() {
  return (
    <>
      <PageHeader
        title="Lịch sử"
        desc="Tra cứu tín hiệu theo ngày / mã / decision (phân trang server-side)."
      />
      <EmptyState
        title="Chưa có dữ liệu"
        hint="Filter + bảng phân trang sẽ được dựng ở E3, đọc từ v4_signals sau khi sync."
      />
    </>
  );
}
