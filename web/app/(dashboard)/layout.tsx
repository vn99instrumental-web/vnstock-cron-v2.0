import Link from "next/link";
import { Suspense } from "react";
import { Nav } from "@/components/nav";
import { VersionBadge } from "@/components/version-badge";
import { SignOutButton } from "@/components/sign-out-button";
import { getUser, isOwner } from "@/lib/supabase/server";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getUser();
  const owner = isOwner(user?.email);

  return (
    <div className="flex min-h-screen flex-col">
      {/* Top bar */}
      <header className="sticky top-0 z-20 border-b border-[var(--color-border)] bg-[var(--color-surface)]/95 shadow-sm backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-3 py-2 md:px-5">
          <Link href="/today" className="flex shrink-0 items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-md bg-[var(--color-accent)] text-xs font-bold text-white">V</span>
            <span className="hidden text-sm font-semibold sm:inline">VNStock Signals</span>
          </Link>

          <div className="min-w-0 flex-1 overflow-x-auto">
            <Nav isOwner={owner} />
          </div>

          {/* Version badge: ẩn trên mobile để nav rộng hơn (thông tin dev, ít giá trị khi xem nhanh) */}
          <div className="hidden shrink-0 sm:block">
            <Suspense fallback={<span className="text-xs text-[var(--color-muted)]">…</span>}>
              <VersionBadge />
            </Suspense>
          </div>

          <div className="hidden shrink-0 items-center gap-2 text-xs text-[var(--color-muted)] md:flex">
            {user ? (
              <>
                <span className="max-w-[160px] truncate" title={user.email ?? ""}>{owner ? "👤 " : ""}{user.email}</span>
                <SignOutButton />
              </>
            ) : (
              <Link href="/login" className="text-[var(--color-accent)] hover:underline">Đăng nhập</Link>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1400px] flex-1 px-3 py-4 md:px-5 md:py-5">{children}</main>
    </div>
  );
}
