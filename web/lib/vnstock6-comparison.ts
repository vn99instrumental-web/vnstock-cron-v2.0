import { fetchGitHubLedgerText } from "@/lib/data-source/github-serving";

interface ProbeReference {
  rows: number;
  unique_symbols: number;
  exchanges: string[];
  columns: string[];
  fpt_present: boolean;
}

interface ProbeResult {
  status: "ok";
  generation: "current" | "6-preview";
  source: "VCI" | "SSI";
  package: string;
  package_version: string;
  oapi_version?: string;
  observed_at: string;
  reference: ProbeReference;
}

export interface Vnstock6Comparison {
  schema_version: 1;
  generated_at: string;
  run: { id: string; url: string; status: "success" };
  current: ProbeResult;
  preview: ProbeResult;
  comparison: {
    overlap_symbols: number;
    union_symbols: number;
    jaccard_percent: number;
    only_current_count: number;
    only_preview_count: number;
    only_current_sample: string[];
    only_preview_sample: string[];
  };
  notes: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isProbe(value: unknown, generation: ProbeResult["generation"], source: ProbeResult["source"]): value is ProbeResult {
  if (!isRecord(value) || value.generation !== generation || value.source !== source || value.status !== "ok") return false;
  const reference = value.reference;
  return isRecord(reference)
    && typeof reference.rows === "number"
    && typeof reference.unique_symbols === "number"
    && Array.isArray(reference.exchanges)
    && Array.isArray(reference.columns)
    && typeof reference.fpt_present === "boolean";
}

function parseComparison(value: unknown): Vnstock6Comparison {
  if (!isRecord(value) || value.schema_version !== 1) throw new Error("Snapshot Gen 6 có schema không được hỗ trợ");
  if (!isProbe(value.current, "current", "VCI") || !isProbe(value.preview, "6-preview", "SSI")) {
    throw new Error("Snapshot Gen 6 thiếu kết quả probe hợp lệ");
  }
  if (!isRecord(value.run) || typeof value.run.url !== "string" || !value.run.url.startsWith("https://github.com/")) {
    throw new Error("Snapshot Gen 6 có liên kết run không hợp lệ");
  }
  if (!isRecord(value.comparison) || typeof value.comparison.overlap_symbols !== "number") {
    throw new Error("Snapshot Gen 6 thiếu số liệu đối chiếu");
  }
  return value as unknown as Vnstock6Comparison;
}

export async function getVnstock6Comparison(): Promise<Vnstock6Comparison> {
  const text = await fetchGitHubLedgerText("output/vnstock6-preview/latest.json");
  return parseComparison(JSON.parse(text) as unknown);
}
