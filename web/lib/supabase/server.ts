// Server Supabase client (Server Components / Route Handlers).
// Dùng anon key + cookie session (RLS áp dụng theo user). KHÔNG dùng service_role ở đây —
// service_role chỉ xuất hiện ở route ghi đặc quyền (E4 Promote), file riêng, server-only.
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Gọi từ Server Component (không set được cookie) — bỏ qua;
            // middleware sẽ refresh session.
          }
        },
      },
    },
  );
}

/** Lấy user hiện tại (null nếu chưa đăng nhập). */
export async function getUser() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user;
}

/** Owner allowlist (ADR-007): chỉ 1 email owner được vào /config + Promote. */
export function isOwner(email: string | null | undefined): boolean {
  const owner = process.env.NEXT_PUBLIC_OWNER_EMAIL?.toLowerCase().trim();
  return !!owner && !!email && email.toLowerCase().trim() === owner;
}
