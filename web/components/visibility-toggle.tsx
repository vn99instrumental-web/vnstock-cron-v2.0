"use client";

import { useState } from "react";

/** Owner đổi chế độ xem app: Công khai ↔ Yêu cầu đăng nhập. Ghi qua /api/settings. */
export function VisibilityToggle({ initial }: { initial: boolean }) {
  const [requireLogin, setRequireLogin] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function apply(next: boolean) {
    if (next === requireLogin || saving) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ require_login: next }),
      });
      const j = await res.json();
      if (!res.ok) {
        setMsg("Lỗi: " + (j?.error ?? res.status));
      } else {
        setRequireLogin(next);
        setMsg("Đã lưu ✓");
      }
    } catch (e) {
      setMsg("Lỗi mạng: " + String(e));
    } finally {
      setSaving(false);
    }
  }

  const Opt = ({ val, label, hint }: { val: boolean; label: string; hint: string }) => {
    const active = requireLogin === val;
    return (
      <button
        onClick={() => apply(val)}
        disabled={saving}
        className={[
          "flex-1 rounded-md border px-3 py-2 text-left transition-colors disabled:opacity-60",
          active
            ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10"
            : "border-[var(--color-border)] hover:bg-black/5 dark:hover:bg-white/5",
        ].join(" ")}
      >
        <div className="flex items-center gap-2 text-sm font-semibold">
          <span className={`grid h-4 w-4 place-items-center rounded-full border ${active ? "border-[var(--color-accent)]" : "border-[var(--color-border)]"}`}>
            {active ? <span className="h-2 w-2 rounded-full bg-[var(--color-accent)]" /> : null}
          </span>
          {label}
        </div>
        <div className="mt-0.5 pl-6 text-[12px] text-[var(--color-muted)]">{hint}</div>
      </button>
    );
  };

  return (
    <div className="card mb-4 p-3">
      <h2 className="text-sm font-semibold">Quyền xem app</h2>
      <p className="mt-0.5 text-[12px] text-[var(--color-muted)]">
        Chọn ai được xem giao diện. Áp dụng ngay (không cần deploy lại).
      </p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <Opt val={false} label="🌐 Công khai" hint="Bất kỳ ai cũng xem được (mặc định)." />
        <Opt val={true} label="🔒 Yêu cầu đăng nhập" hint="Phải đăng nhập mới xem được mọi trang." />
      </div>
      {msg ? <div className="mt-2 text-[12px] text-[var(--color-muted)]">{msg}</div> : null}
      <p className="mt-2 text-[11px] italic text-[var(--color-muted)]">
        Lưu ý: chế độ này ẩn GIAO DIỆN web. Dữ liệu thô trong Supabase vẫn đọc được qua anon key
        (theo RLS công khai hiện tại) — muốn khoá cả dữ liệu cần siết RLS riêng.
      </p>
    </div>
  );
}
