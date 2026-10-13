import { createClient } from "@supabase/supabase-js";
import { DEFAULT_SCORING_VERSION } from "@/lib/scoring-versions";

const CURRENT_TTL_SECONDS = 5 * 60;
const HISTORICAL_TTL_SECONDS = 7 * 24 * 60 * 60;

type NextFetchInit = RequestInit & {
  next?: { revalidate?: number; tags?: string[] };
};

/**
 * Read-only Supabase client for public dashboard data.
 * GET responses are stored in the Next.js/Vercel Data Cache per query URL.
 * Never use this client for user-specific data or writes.
 */
export function createCachedPublicClient(scope: string, scoringVersion: string) {
  const revalidate = scoringVersion === DEFAULT_SCORING_VERSION
    ? CURRENT_TTL_SECONDS
    : HISTORICAL_TTL_SECONDS;
  const tags = ["dashboard-data", `dashboard-${scope}`, `scoring-${scoringVersion}`];

  const cachedFetch: typeof fetch = (input, init = {}) => {
    const options = init as NextFetchInit;
    return fetch(input, {
      ...options,
      cache: "force-cache",
      next: {
        ...options.next,
        revalidate,
        tags: [...new Set([...(options.next?.tags ?? []), ...tags])],
      },
    });
  };

  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      global: { fetch: cachedFetch },
    },
  );
}