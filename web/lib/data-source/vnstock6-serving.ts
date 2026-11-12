import { fetchGitHubLedgerText, githubServing } from "@/lib/data-source/github-serving";
import type { DashboardDataSource } from "@/lib/data-source/source";

const SAFE_SYMBOL = /^[A-Z0-9]{1,10}$/;

export interface Vnstock6DashboardManifest {
  schema_version: 1;
  mode: "bridge" | "native";
  generated_at: string;
  source: "SSI";
  package_version: string;
  oapi_version: string;
  upstream: "github" | null;
  symbols: string[];
  capabilities: Record<string, "bridge" | "native" | "unavailable">;
  flow: {
    run_id: string;
    run_url: string;
    stages: Array<{ name: string; status: "success" | "pending" | "failed"; mode: "bridge" | "native" }>;
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseManifest(value: unknown): Vnstock6DashboardManifest {
  if (!isRecord(value) || value.schema_version !== 1) {
    throw new Error("VNStock 6 dashboard manifest has an unsupported schema");
  }
  if (value.mode !== "bridge" && value.mode !== "native") {
    throw new Error("VNStock 6 dashboard manifest has an unsupported mode");
  }
  if (value.source !== "SSI" || typeof value.package_version !== "string" || typeof value.oapi_version !== "string") {
    throw new Error("VNStock 6 dashboard manifest is missing package provenance");
  }
  if (!Array.isArray(value.symbols) || value.symbols.some((symbol) => typeof symbol !== "string" || !SAFE_SYMBOL.test(symbol))) {
    throw new Error("VNStock 6 dashboard manifest contains an invalid symbol");
  }
  if (!isRecord(value.capabilities)) {
    throw new Error("VNStock 6 dashboard manifest is missing capabilities");
  }
  const capabilityValues = Object.values(value.capabilities);
  if (capabilityValues.some((item) => item !== "bridge" && item !== "native" && item !== "unavailable")) {
    throw new Error("VNStock 6 dashboard manifest has an invalid capability");
  }
  if (!isRecord(value.flow) || typeof value.flow.run_url !== "string" || !value.flow.run_url.startsWith("https://github.com/") || !Array.isArray(value.flow.stages)) {
    throw new Error("VNStock 6 dashboard manifest is missing flow stages");
  }
  const validStages = value.flow.stages.every((stage) => isRecord(stage)
    && typeof stage.name === "string"
    && (stage.status === "success" || stage.status === "pending" || stage.status === "failed")
    && (stage.mode === "bridge" || stage.mode === "native"));
  if (!validStages) throw new Error("VNStock 6 dashboard manifest has an invalid flow stage");
  return value as unknown as Vnstock6DashboardManifest;
}

export async function getVnstock6DashboardManifest(): Promise<Vnstock6DashboardManifest> {
  const text = await fetchGitHubLedgerText("output/vnstock6-preview/dashboard.json");
  const manifest = parseManifest(JSON.parse(text) as unknown);
  if (process.env.VNSTOCK6_NATIVE_MODE !== "1") return manifest;

  const nativeToday = await fetchNative<{ signals?: unknown[] }>("today/v6.0-native.json");
  const symbols = Array.from(new Set((nativeToday.signals ?? []).flatMap((row) => {
    if (!isRecord(row) || typeof row.symbol !== "string") return [];
    const symbol = row.symbol.toUpperCase();
    return SAFE_SYMBOL.test(symbol) ? [symbol] : [];
  }))).sort();
  if (!symbols.length) throw new Error("VNStock 6 native serving has no valid symbols");

  return {
    ...manifest,
    mode: "native",
    package_version: "6.0.0",
    oapi_version: "0.1.1",
    upstream: null,
    symbols,
    capabilities: Object.fromEntries(Object.keys(manifest.capabilities).map((key) => [key, "native"])),
  };
}

function filterSymbolRows<T>(rows: T[], allowed: Set<string>): T[] {
  return rows.filter((row) => {
    if (!isRecord(row) || typeof row.symbol !== "string") return false;
    return allowed.has(row.symbol.toUpperCase());
  });
}

async function bridgeContext() {
  const manifest = await getVnstock6DashboardManifest();
  if (manifest.mode !== "bridge" || manifest.upstream !== "github") {
    throw new Error("VNStock 6 bridge serving is not available");
  }
  return { manifest, allowed: new Set(manifest.symbols) };
}

async function fetchNative<T>(path: string): Promise<T> {
  const text = await fetchGitHubLedgerText(`output/serving/vnstock6/current/${path}`);
  return JSON.parse(text) as T;
}

export const vnstock6Serving = {
  metadata: async () => {
    const manifest = await getVnstock6DashboardManifest();
    if (manifest.mode === "native") return fetchNative<Awaited<ReturnType<typeof githubServing.metadata>>>("metadata.json");
    const [{ manifest: bridge }, metadata] = await Promise.all([bridgeContext(), githubServing.metadata()]);
    return { ...metadata, release_id: `vnstock6-${bridge.generated_at}`, source_provenance: "vnstock6-bridge", generation: "6-preview", market_source: bridge.source };
  },
  today: async (version: string) => {
    const manifest = await getVnstock6DashboardManifest();
    if (manifest.mode === "native") return fetchNative<Awaited<ReturnType<typeof githubServing.today>>>(`today/${version}.json`);
    const [{ allowed }, snapshot] = await Promise.all([bridgeContext(), githubServing.today(version)]);
    return { ...snapshot, signals: filterSymbolRows(snapshot.signals, allowed) };
  },
  buy: async (version: string) => {
    const manifest = await getVnstock6DashboardManifest();
    if (manifest.mode === "native") return fetchNative<Awaited<ReturnType<typeof githubServing.buy>>>(`buy/${version}.json`);
    const [{ allowed }, snapshot] = await Promise.all([bridgeContext(), githubServing.buy(version)]);
    return { ...snapshot, signals: filterSymbolRows(snapshot.signals, allowed) };
  },
  analysis: async (version: string) => {
    const manifest = await getVnstock6DashboardManifest();
    if (manifest.mode === "native") return fetchNative<Awaited<ReturnType<typeof githubServing.analysis>>>(`analysis/${version}.json`);
    const [{ allowed }, snapshot] = await Promise.all([bridgeContext(), githubServing.analysis(version)]);
    return { ...snapshot, results: filterSymbolRows(snapshot.results, allowed) };
  },
  history: async (version: string) => {
    const manifest = await getVnstock6DashboardManifest();
    if (manifest.mode === "native") return fetchNative<Awaited<ReturnType<typeof githubServing.history>>>(`history/${version}.json`);
    const [{ allowed }, snapshot] = await Promise.all([bridgeContext(), githubServing.history(version)]);
    const rows = filterSymbolRows(snapshot.rows, allowed);
    return { ...snapshot, rows, count: rows.length };
  },
  chart: async (version: string, symbol: string) => {
    const manifest = await getVnstock6DashboardManifest();
    const normalized = symbol.toUpperCase();
    if (!manifest.symbols.includes(normalized)) throw new Error("Symbol is outside the VNStock 6 universe");
    if (manifest.mode === "native") return fetchNative<Awaited<ReturnType<typeof githubServing.chart>>>(`charts/${version}/${normalized}.json`);
    return githubServing.chart(version, normalized);
  },
};
export function servingForSource(source: DashboardDataSource) {
  if (source === "supabase") throw new Error("Supabase does not use the serving adapter");
  return source === "vnstock6" ? vnstock6Serving : githubServing;
}

export function isServingSource(source: DashboardDataSource): source is Exclude<DashboardDataSource, "supabase"> {
  return source !== "supabase";
}