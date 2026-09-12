// Helper refresh session cho middleware + gate /config (ADR-007).
// Fail-safe: nếu thiếu env hoặc Supabase lỗi → KHÔNG sập site; chỉ chặn /config (fail-closed),
// còn route public vẫn render bình thường.
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

function redirectToLogin(request: NextRequest) {
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(url);
}

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const { pathname } = request.nextUrl;

  // Thiếu env → không thể xác thực. Không sập: chặn /config, public vẫn chạy.
  if (!url || !anon) {
    if (isProtected(pathname)) return redirectToLogin(request);
    return response;
  }

  try {
    const supabase = createServerClient(url, anon, {
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
    });

    // QUAN TRỌNG: getUser() refresh token; đừng chèn logic giữa createServerClient và đây.
    const {
      data: { user },
    } = await supabase.auth.getUser();

    const owner = process.env.NEXT_PUBLIC_OWNER_EMAIL?.toLowerCase().trim();
    const isOwner =
      !!owner && !!user?.email && user.email.toLowerCase().trim() === owner;

    if (isProtected(pathname) && !isOwner) {
      return redirectToLogin(request);
    }
    return response;
  } catch {
    // Supabase lỗi (mạng/khoá sai) → fail-closed cho /config, còn lại vẫn render.
    if (isProtected(pathname)) return redirectToLogin(request);
    return response;
  }
}
