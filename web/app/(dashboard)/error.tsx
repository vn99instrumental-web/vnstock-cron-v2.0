"use client";

import { useEffect } from "react";

// Error boundary cho các trang dashboard: thay màn hình trắng "Application error"
// bằng thông báo đọc được + nút thử lại. Với lỗi phía client, error.message là lỗi thật.
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log ra console để có stack đầy đủ khi cần soi.
    console.error("[dashboard error]", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-lg px-4 py-16 text-center">
      <div className="text-3xl">⚠️</div>
      <h1 className="mt-3 text-lg font-semibold">Có lỗi khi hiển thị trang</h1>
      <p className="mt-1 text-sm text-[var(--color-muted)]">
        Thử tải lại. Nếu vẫn lỗi, chụp màn hình phần chi tiết bên dưới gửi lại giúp nhé.
      </p>

      <div className="mt-4 flex justify-center gap-2">
        <button
          onClick={() => reset()}
          className="min-h-[40px] rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white active:opacity-80"
        >
          ↻ Thử lại
        </button>
        <button
          onClick={() => { if (typeof window !== "undefined") window.location.href = "/buy"; }}
          className="min-h-[40px] rounded-md border border-[var(--color-border)] px-4 py-2 text-sm font-medium active:bg-black/5 dark:active:bg-white/5"
        >
          Về trang Mua
        </button>
      </div>

      <details className="mt-5 text-left">
        <summary className="cursor-pointer select-none text-xs text-[var(--color-muted)]">Chi tiết lỗi (để gửi lại)</summary>
        <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md border border-[var(--color-border)] bg-black/[0.03] p-2 text-left text-[11px] dark:bg-white/[0.05]">
{String(error?.message || "(không có message)")}
{error?.digest ? `\n\ndigest: ${error.digest}` : ""}
        </pre>
      </details>
    </div>
  );
}
