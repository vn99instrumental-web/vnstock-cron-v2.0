// Helper refresh session cho middleware + gate /config (ADR-007).
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

type CookieToSet = { name: string; value: string; options: CookieOptions };

// Route cần đăng nhập owner. Public: today/history/ic + trang gốc.
const PROTECTED_PREFIXES = ["/config"];

function isProtected(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );
}

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: CookieToSet[]) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  // QUAN TRỌNG: getUser() refresh token; đừng chèn logic giữa createServerClient và đây.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;
  const owner = process.env.NEXT_PUBLIC_OWNER_EMAIL?.toLowerCase().trim();
  const isOwner =
    !!owner && !!user?.email && user.email.toLowerCase().trim() === owner;

  // Chưa đăng nhập / không phải owner → chặn route bảo vệ, đẩy về /login.
  if (isProtected(pathname) && !isOwner) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  return response;
}
