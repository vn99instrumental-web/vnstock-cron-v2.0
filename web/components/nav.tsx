"use client";

import Link, { useLinkStatus } from "next/link";
import { usePathname } from "next/navigation";

type NavLink = { href: string; label: string; icon: string; owner?: boolean };

const LINKS: NavLink[] = [
  { href: "/buy", label: "Mua", icon: "▲" },
  { href: "/phan-tich", label: "Phân tích", icon: "◑" },
  { href: "/today", label: "Hôm nay", icon: "●" },
  { href: "/history", label: "Lịch sử", icon: "◷" },
  { href: "/ic", label: "Chất lượng (IC)", icon: "▤" },
  { href: "/config", label: "Cấu hình", icon: "⚙", owner: true },
];

// Icon chỉ báo: đang điều hướng tới link vừa bấm → spinner (phản hồi tức thì).
function LinkIcon({ icon }: { icon: string }) {
  const { pending } = useLinkStatus();
  return pending ? (
    <span aria-hidden className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border border-current border-t-transparent opacity-80" />
  ) : (
    <span aria-hidden className="text-xs opacity-70">{icon}</span>
  );
}

export function Nav({ isOwner }: { isOwner: boolean }) {
  const pathname = usePathname();

  return (
    <nav className="flex gap-1">
      {LINKS.filter((l) => !l.owner || isOwner).map((l) => {
        const active = pathname === l.href || pathname.startsWith(l.href + "/");
        return (
          <Link
            key={l.href}
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
            <LinkIcon icon={l.icon} />
            <span>{l.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
