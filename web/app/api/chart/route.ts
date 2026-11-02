import { NextRequest, NextResponse } from "next/server";
import { githubServing } from "@/lib/data-source/github-serving";
import { getDashboardDataSource } from "@/lib/data-source/source";
import { createClient } from "@/lib/supabase/server";

const SAFE_VERSION = /^v\d+(?:\.\d+)?$/;
const SAFE_SYMBOL = /^[A-Z0-9]{1,10}$/;

async function loadSupabase(version: string, symbol: string) {
  const supabase = await createClient();
  const [signals, ohlc] = await Promise.all([
    supabase.from("v4_signals")
      .select("signal_date, snap_time, decision, price:breakdown->>price")
      .eq("symbol", symbol).eq("scoring_version", version)
      .order("signal_date", { ascending: true }).order("snap_time", { ascending: true }),
    supabase.from("v4_ohlc")
      .select("date, open, high, low, close")
      .eq("symbol", symbol).order("date", { ascending: true }),
  ]);
  if (signals.error) throw signals.error;
  if (ohlc.error) throw ohlc.error;
  return { signals: signals.data ?? [], ohlc: ohlc.data ?? [] };
}

export async function GET(request: NextRequest) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const version = request.nextUrl.searchParams.get("version") ?? "";
  const symbol = (request.nextUrl.searchParams.get("symbol") ?? "").toUpperCase();
  if (!SAFE_VERSION.test(version) || !SAFE_SYMBOL.test(symbol)) {
    return NextResponse.json({ error: "Invalid version or symbol" }, { status: 400 });
  }

  try {
    if (await getDashboardDataSource() === "github") {
      try {
        return NextResponse.json(await githubServing.chart(version, symbol));
      } catch {
        // A partial/old release must not break the chart while Supabase is available.
      }
    }
    return NextResponse.json(await loadSupabase(version, symbol));
  } catch {
    return NextResponse.json({ error: "Chart data unavailable" }, { status: 503 });
  }
}
