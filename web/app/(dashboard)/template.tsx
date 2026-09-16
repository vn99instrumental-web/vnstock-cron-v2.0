// Template re-mount mỗi lần điều hướng → áp animation fade-in cho nội dung trang.
export default function DashboardTemplate({ children }: { children: React.ReactNode }) {
  return <div className="page-enter">{children}</div>;
}
