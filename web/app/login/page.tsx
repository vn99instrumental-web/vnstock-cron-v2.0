"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/today";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) {
      setError("Đăng nhập thất bại: " + error.message);
      return;
    }
    router.refresh();
    router.push(next);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <label className="text-sm">
        Email
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm"
          autoComplete="email"
        />
      </label>
      <label className="text-sm">
        Mật khẩu
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm"
          autoComplete="current-password"
        />
      </label>
      {error ? (
        <p className="text-sm text-[var(--color-sell)]">{error}</p>
      ) : null}
      <button
        type="submit"
        disabled={loading}
        className="mt-1 rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
      >
        {loading ? "Đang đăng nhập…" : "Đăng nhập"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <div className="mb-4 flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-[var(--color-accent)] text-sm font-bold text-white">
            V
          </span>
          <span className="text-sm font-semibold">VNStock Signals — Đăng nhập</span>
        </div>
        <p className="mb-4 text-xs text-[var(--color-muted)]">
          Chỉ owner. Đăng nhập để vào cấu hình chấm điểm. Xem tín hiệu công khai
          không cần đăng nhập.
        </p>
        <Suspense fallback={<p className="text-sm text-[var(--color-muted)]">…</p>}>
          <LoginForm />
        </Suspense>
        <Link
          href="/today"
          className="mt-4 block text-center text-xs text-[var(--color-accent)] hover:underline"
        >
          ← Về trang tín hiệu
        </Link>
      </div>
    </div>
  );
}
