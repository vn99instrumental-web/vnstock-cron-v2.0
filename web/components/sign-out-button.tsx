"use client";

import { createClient } from "@/lib/supabase/client";

export function SignOutButton() {
  async function signOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    // Hard reload để server render lại trạng thái đã đăng xuất.
    window.location.assign("/today");
  }

  return (
    <button
      onClick={signOut}
      className="w-fit rounded-md border border-[var(--color-border)] px-2 py-1 text-xs text-[var(--color-muted)] hover:text-[var(--color-ink)]"
    >
      Đăng xuất
    </button>
  );
}
