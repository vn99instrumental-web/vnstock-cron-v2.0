// Skeleton hiển thị ngay khi chuyển trang (server component đang tải) → đỡ "khựng".
export default function DashboardLoading() {
  return (
    <div className="animate-pulse space-y-3 py-2">
      <div className="h-6 w-40 rounded bg-black/10 dark:bg-white/10" />
      <div className="flex gap-2">
        <div className="h-16 flex-1 rounded-lg bg-black/5 dark:bg-white/5" />
        <div className="h-16 flex-1 rounded-lg bg-black/5 dark:bg-white/5" />
        <div className="h-16 flex-1 rounded-lg bg-black/5 dark:bg-white/5" />
      </div>
      <div className="h-40 rounded-lg bg-black/5 dark:bg-white/5" />
      <div className="h-64 rounded-lg bg-black/5 dark:bg-white/5" />
    </div>
  );
}
