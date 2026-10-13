"use client";

import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";
const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<Theme, string> = { system: "Theo máy", light: "Sáng", dark: "Tối" };

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => {
    const saved = localStorage.getItem("vnstock-theme");
    const next = saved === "light" || saved === "dark" ? saved : "system";
    setTheme(next);
    if (next === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = next;
  }, []);
  function cycle() {
    const next = NEXT[theme];
    setTheme(next);
    if (next === "system") {
      localStorage.removeItem("vnstock-theme");
      document.documentElement.removeAttribute("data-theme");
    } else {
      localStorage.setItem("vnstock-theme", next);
      document.documentElement.dataset.theme = next;
    }
  }
  return <button type="button" onClick={cycle} aria-label={`Đổi giao diện, hiện tại ${LABEL[theme]}`} className="grid h-8 w-8 place-items-center rounded-md border border-[var(--color-border)] text-sm text-[var(--color-muted)]" title={`Giao diện: ${LABEL[theme]}`}>{theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}</button>;
}