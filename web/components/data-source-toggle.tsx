"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { DashboardDataSource } from "@/lib/data-source/source";

export function DataSourceToggle({ source }: { source: DashboardDataSource }) {
  const router = useRouter();
  const [value, setValue] = useState(source);
  const [pending, startTransition] = useTransition();

  async function switchSource(next: DashboardDataSource) {
    const previous = value;
    setValue(next);
    const response = await fetch("/api/data-source", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ source: next }),
    });
    if (!response.ok) {
      setValue(previous);
      return;
    }
    startTransition(() => router.refresh());
  }

  return (
    <div className="hidden items-center gap-0.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-0.5 text-[10px] lg:flex" role="group" aria-label="Nguá»“n dá»¯ liá»‡u dashboard">
      {(["supabase", "github"] as const).map((sourceOption) => {
        const active = value === sourceOption;
        return (
          <button
            key={sourceOption}
            type="button"
            aria-pressed={active}
            disabled={pending || active}
            onClick={() => void switchSource(sourceOption)}
            className={`min-h-7 rounded-md px-2.5 font-semibold transition-colors ${
              active
                ? "bg-[var(--color-accent)] text-white shadow-sm"
                : "text-[var(--color-muted)] hover:bg-black/5 hover:text-[var(--color-ink)] dark:hover:bg-white/5"
            } disabled:cursor-default`}
          >
            {sourceOption === "supabase" ? "Supabase" : "GitHub"}
          </button>
        );
      })}
    </div>
  );
}
