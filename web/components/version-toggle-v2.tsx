"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = ["/buy", "/phan-tich", "/today", "/history", "/ic"] as const;

export function VersionToggleV2() {
  const pathname = usePathname();
  const isSsi = pathname === "/ssi" || pathname.startsWith("/ssi/");
  const unprefixed = isSsi ? pathname.slice(4) || "/today" : pathname;
  const tab = TABS.find((candidate) =>
    unprefixed === candidate || unprefixed.startsWith(candidate + "/")
  ) ?? "/today";
  const versions = [
    { id: "gen6", href: tab, desktop: "Th\u1ebf h\u1ec7 6", mobile: "Gen 6" },
    { id: "ssi", href: `/ssi${tab}`, desktop: "SSI \u0111\u1ed9c l\u1eadp", mobile: "SSI" },
  ] as const;

  return (
    <nav
      className="flex items-center gap-0.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-0.5 text-[10px]"
      aria-label="Scoring versions"
    >
      {versions.map((version) => {
        const active = (isSsi ? "ssi" : "gen6") === version.id;
        return (
          <Link
            key={version.id}
            href={version.href}
            aria-current={active ? "page" : undefined}
            className={`grid min-h-7 place-items-center rounded-md px-2 font-semibold transition-colors sm:px-2.5 ${
              active
                ? "bg-[var(--color-accent)] text-white shadow-sm"
                : "text-[var(--color-muted)] hover:bg-black/5 hover:text-[var(--color-ink)] dark:hover:bg-white/5"
            }`}
          >
            <span className="sm:hidden">{version.mobile}</span>
            <span className="hidden sm:inline">{version.desktop}</span>
          </Link>
        );
      })}
    </nav>
  );
}
