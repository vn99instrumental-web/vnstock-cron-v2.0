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
    <div className="min-h-screen md:grid md:grid-cols-[220px_1fr]">
      {/* Sidebar (desktop) / top-bar (mobile) */}
      <aside className="border-b border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 md:border-b-0 md:border-r md:py-5">
        <div className="mb-4 flex items-center justify-between md:mb-6">
          <Link href="/today" className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-[var(--color-accent)] text-sm font-bold text-white">
              V
            </span>
            <span className="text-sm font-semibold">VNStock Signals</span>
          </Link>
        </div>
        <Nav isOwner={owner} />
        <div className="mt-4 border-t border-[var(--color-border)] pt-3 text-xs text-[var(--color-muted)] md:mt-6">
          {user ? (
            <div className="flex flex-col gap-2">
              <span className="truncate" title={user.email ?? ""}>
                {owner ? "👤 " : ""}
                {user.email}
              </span>
              <SignOutButton />
            </div>
          ) : (
            <Link href="/login" className="text-[var(--color-accent)] hover:underline">
              Đăng nhập (owner)
            </Link>
          )}
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 md:px-6">
          <span className="text-xs text-[var(--color-muted)]">
            Pipeline v2f_v4 · nguồn chân lý: Python + ledger
          </span>
          <Suspense
            fallback={
              <span className="text-xs text-[var(--color-muted)]">…</span>
            }
          >
            <VersionBadge />
          </Suspense>
        </header>
        <main className="flex-1 px-4 py-5 md:px-6 md:py-6">{children}</main>
      </div>
    </div>
  );
}
