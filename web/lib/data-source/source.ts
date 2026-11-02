import { cookies } from "next/headers";

export type DashboardDataSource = "supabase" | "github";

export const DATA_SOURCE_COOKIE = "dashboard_data_source";

export function parseDashboardDataSource(value: unknown): DashboardDataSource | null {
  return value === "supabase" || value === "github" ? value : null;
}

export function defaultDashboardDataSource(): DashboardDataSource {
  return parseDashboardDataSource(process.env.DASHBOARD_DATA_SOURCE) ?? "supabase";
}

export async function getDashboardDataSource(): Promise<DashboardDataSource> {
  const store = await cookies();
  return parseDashboardDataSource(store.get(DATA_SOURCE_COOKIE)?.value)
    ?? defaultDashboardDataSource();
}
