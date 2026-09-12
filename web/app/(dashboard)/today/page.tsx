import { PageHeader, EmptyState } from "@/components/ui";

export default function TodayPage() {
  return (
    <>
      <PageHeader
        title="Hôm nay"
        desc="Tín hiệu của run mới nhất (signal_date + snap_time lớn nhất)."
      />
      <EmptyState
        title="Chưa có dữ liệu tín hiệu"
        hint="Bảng v4_signals đang rỗng. Data sẽ lên bảng sau khi sync (E1) chạy trên GitHub Actions. Bảng danh sách decision/score/regime sẽ được dựng ở E3."
      />
    </>
  );
}
