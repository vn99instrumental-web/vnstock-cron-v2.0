"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/today", label: "Hôm nay", icon: "●" },
  { href: "/history", label: "Lịch sử", icon: "◷" },
  { href: "/ic", label: "Chất lượng (IC)", icon: "▤" },
  { href: "/config", label: "Cấu hình", icon: "⚙", owner: true },
] as const;

export function Nav({ isOwner }: { isOwner: boolean }) {
  const pathname = usePathname();

  return (
    <nav className="flex gap-1 md:flex-col md:gap-0.5">
      {LINKS.filter((l) => !l.owner || isOwner).map((l) => {
        const active = pathname === l.href || pathname.startsWith(l.href + "/");
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={[
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-[var(--color-accent)] text-white"
                : "text-[var(--color-muted)] hover:bg-black/5 hover:text-[var(--color-ink)] dark:hover:bg-white/5",
            ].join(" ")}
          >
            <span aria-hidden className="text-xs opacity-70">
              {l.icon}
            </span>
            <span>{l.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
