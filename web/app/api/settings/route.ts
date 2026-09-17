// SERVER-ONLY. Ghi cài đặt app (require_login) → bảng app_settings bằng
// SUPABASE_SERVICE_ROLE_KEY. Gate: chỉ owner (Supabase Auth). KHÔNG import ở client.
import { NextResponse } from "next/server";
import { getUser, isOwner } from "@/lib/supabase/server";

export const runtime = "nodejs";

export async function POST(request: Request) {
  // Same-origin guard (CSRF defense-in-depth).
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (origin && host && new URL(origin).host !== host) {
    return NextResponse.json({ error: "Cross-origin bị chặn." }, { status: 403 });
  }

  // Chỉ owner.
  const user = await getUser();
  if (!isOwner(user?.email)) {
    return NextResponse.json({ error: "Chỉ owner được đổi cài đặt." }, { status: 403 });
  }

  let body: { require_login?: boolean };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Body JSON không hợp lệ." }, { status: 400 });
  }
  if (typeof body.require_login !== "boolean") {
    return NextResponse.json({ error: "Thiếu require_login (boolean)." }, { status: 400 });
  }

  const sbUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const svcKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!sbUrl || !svcKey) {
    return NextResponse.json({ error: "Server chưa cấu hình SUPABASE_SERVICE_ROLE_KEY." }, { status: 500 });
  }

  const res = await fetch(`${sbUrl}/rest/v1/app_settings?id=eq.true`, {
    method: "PATCH",
    headers: {
      apikey: svcKey,
      Authorization: `Bearer ${svcKey}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({
      require_login: body.require_login,
      updated_at: new Date().toISOString(),
      updated_by: user!.email ?? null,
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    return NextResponse.json({ error: `Ghi cài đặt lỗi ${res.status}`, detail: t.slice(0, 200) }, { status: 502 });
  }

  return NextResponse.json({ ok: true, require_login: body.require_login });
}
