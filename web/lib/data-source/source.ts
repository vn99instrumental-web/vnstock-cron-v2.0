import { cookies } from "next/headers";

export type DashboardDataSource = "supabase" | "github" | "vnstock6" | "ssi";

export const DATA_SOURCE_COOKIE = "dashboard_data_source";

export function parseDashboardDataSource(value: unknown): DashboardDataSource | null {
  // Supabase and GitHub remain implementation details for auth/auditing only.
  // They are no longer selectable dashboard versions on Vercel.
  return value === "vnstock6" ? value : null;
}

export function defaultDashboardDataSource(): DashboardDataSource {
  return parseDashboardDataSource(process.env.DASHBOARD_DATA_SOURCE) ?? "vnstock6";
}

export async function getDashboardDataSource(): Promise<DashboardDataSource> {
  const store = await cookies();
  return parseDashboardDataSource(store.get(DATA_SOURCE_COOKIE)?.value)
    ?? defaultDashboardDataSource();
}
