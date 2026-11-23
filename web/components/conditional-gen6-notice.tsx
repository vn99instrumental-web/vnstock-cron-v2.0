"use client";

import { usePathname } from "next/navigation";

export function ConditionalGen6Notice({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/ssi" || pathname.startsWith("/ssi/")) return null;
  return children;
}
