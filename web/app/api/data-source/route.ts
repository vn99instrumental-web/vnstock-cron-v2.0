import { NextResponse } from "next/server";
import { getUser, isOwner } from "@/lib/supabase/server";
import {
  DATA_SOURCE_COOKIE,
  parseDashboardDataSource,
} from "@/lib/data-source/source";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const user = await getUser();
  if (!user || !isOwner(user.email)) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const source = parseDashboardDataSource(
    body && typeof body === "object" ? (body as { source?: unknown }).source : null,
  );
  if (!source) {
    return NextResponse.json({ error: "Unsupported data source" }, { status: 400 });
  }

  const response = NextResponse.json({ ok: true, source });
  response.cookies.set(DATA_SOURCE_COOKIE, source, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 30 * 24 * 60 * 60,
  });
  return response;
}
