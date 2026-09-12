// Browser Supabase client — CHỈ dùng anon/publishable key (an toàn ra client).
// KHÔNG bao giờ import service_role ở file này.
import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
