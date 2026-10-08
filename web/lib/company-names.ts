import "server-only";

import industryMap from "../../output/industry_map.json";

type IndustryEntry = {
  symbol?: string;
  organ_name?: string;
  organ_short_name?: string;
};

const companyNameBySymbol = new Map<string, string>();

for (const entry of industryMap as IndustryEntry[]) {
  const symbol = entry.symbol?.trim().toUpperCase();
  const companyName = entry.organ_short_name?.trim() || entry.organ_name?.trim();
  if (symbol && companyName) companyNameBySymbol.set(symbol, companyName);
}

export function getCompanyName(symbol: string): string | null {
  return companyNameBySymbol.get(symbol.trim().toUpperCase()) ?? null;
}
