import fs from "node:fs";
import path from "node:path";

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${name}`);
  return process.argv[index + 1];
}

function packageVersion(metadataRoot, packageName) {
  const normalized = packageName.replaceAll("-", "_");
  if (!fs.existsSync(metadataRoot)) return "unknown";
  const directory = fs.readdirSync(metadataRoot).find(
    (name) => name.toLowerCase().startsWith(`${normalized.toLowerCase()}-`) && name.endsWith(".dist-info"),
  );
  if (!directory) return "unknown";
  const metadata = fs.readFileSync(path.join(metadataRoot, directory, "METADATA"), "utf8");
  return metadata.match(/^Version:\s*(.+)$/m)?.[1]?.trim() ?? "unknown";
}

const input = argument("--input");
const metadataRoot = argument("--metadata-root");
const output = argument("--output");
const rows = JSON.parse(fs.readFileSync(input, "utf8"));
if (!Array.isArray(rows) || rows.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
  throw new Error("Current production industry snapshot must be a list of objects");
}

const symbols = [...new Set(rows.map((row) => String(row.symbol ?? "").trim().toUpperCase()).filter(Boolean))].sort();
const exchanges = [...new Set(rows.map((row) => String(row.exchange ?? "").trim().toUpperCase()).filter(Boolean))].sort();
const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].sort();
const payload = {
  schema_version: 1,
  status: "ok",
  generation: "current",
  source: "VCI",
  data_origin: "production-snapshot",
  package: "vnstock_data",
  package_version: packageVersion(metadataRoot, "vnstock_data"),
  observed_at: new Date().toISOString(),
  reference: {
    rows: rows.length,
    symbols,
    exchanges,
    columns,
    fpt_present: symbols.includes("FPT"),
  },
};

fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(`Current VCI production snapshot: ${symbols.length} unique symbols`);
