"use client";

import Link, { useLinkStatus } from "next/link";
import { usePathname } from "next/navigation";

type NavLink = { href: string; label: string; short: string; icon: string; owner?: boolean };

const LINKS: NavLink[] = [
  { href: "/buy", label: "Mua", short: "Mua", icon: "▲" },
  { href: "/phan-tich", label: "Phân tích", short: "Phân tích", icon: "◑" },
  { href: "/today", label: "Hôm nay", short: "Hôm nay", icon: "●" },
  { href: "/history", label: "Lịch sử", short: "Lịch sử", icon: "◷" },
  { href: "/ic", label: "Chất lượng (IC)", short: "IC", icon: "▤" },
  { href: "/config", label: "Cấu hình", short: "Cấu hình", icon: "⚙", owner: true },
];

function useActive(href: string) {
  const pathname = usePathname();
  return pathname === href || pathname.startsWith(href + "/");
}

// Spinner khi đang điều hướng tới link vừa bấm (phản hồi tức thì).
function PendingIcon({ icon, size = "text-xs" }: { icon: string; size?: string }) {
  const { pending } = useLinkStatus();
  return pending ? (
    <span aria-hidden className="inline-block h-3.5 w-3.5 shrink-0 animate-spin rounded-full border border-current border-t-transparent opacity-80" />
  ) : (
    <span aria-hidden className={`${size} opacity-70`}>{icon}</span>
  );
}

/** Nav ngang trên đầu — dùng cho desktop (md+). */
export function Nav({ isOwner }: { isOwner: boolean }) {
  return (
    <nav className="flex gap-1">
      {LINKS.filter((l) => !l.owner || isOwner).map((l) => <TopItem key={l.href} l={l} />)}
    </nav>
  );
}

function TopItem({ l }: { l: NavLink }) {
  const active = useActive(l.href);
  return (
    <Link
      href={l.href}
      prefetch
      aria-current={active ? "page" : undefined}
      className={[
        "flex min-h-[38px] shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition-colors active:scale-[0.97]",
        active
          ? "bg-[var(--color-accent)] text-white"
          : "text-[var(--color-muted)] hover:bg-black/5 hover:text-[var(--color-ink)] active:bg-black/10 dark:hover:bg-white/5 dark:active:bg-white/10",
      ].join(" ")}
    >
      <PendingIcon icon={l.icon} />
      <span>{l.label}</span>
    </Link>
  );
}

/** Thanh tab dưới đáy — cho mobile, các tab chia đều auto-fit màn hình. */
export function MobileNav({ isOwner }: { isOwner: boolean }) {
  const links = LINKS.filter((l) => !l.owner || isOwner);
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-30 flex border-t border-[var(--color-border)] bg-[var(--color-surface)]/95 shadow-[0_-1px_3px_rgba(16,24,40,0.06)] backdrop-blur md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {links.map((l) => <BottomItem key={l.href} l={l} />)}
    </nav>
  );
}

function BottomItem({ l }: { l: NavLink }) {
  const active = useActive(l.href);
  return (
    <Link
      href={l.href}
      prefetch
      aria-current={active ? "page" : undefined}
      className={[
        "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[10px] font-medium transition-colors active:scale-[0.95]",
        active ? "text-[var(--color-accent)]" : "text-[var(--color-muted)] active:text-[var(--color-ink)]",
      ].join(" ")}
    >
      <PendingIcon icon={l.icon} size="text-base" />
      <span className="max-w-full truncate px-0.5">{l.short}</span>
    </Link>
  );
}
