// SERVER-ONLY (ADR-005). Promote 1 config → GHI active.json vào repo (GITHUB_TOKEN)
// + ghi v4_scoring_configs (SUPABASE_SERVICE_ROLE_KEY). KHÔNG bao giờ import ở client.
// Gate: chỉ owner (Supabase Auth). Validate cấu trúc trước khi ghi. One-change-per-cycle.
import { NextResponse } from "next/server";
import { getUser, isOwner } from "@/lib/supabase/server";
import { FACTORS, type ScoringConfig } from "@/lib/scoring/simulate";

export const runtime = "nodejs";

const CONFIG_PATH = process.env.CONFIG_PATH || "config/scoring/active.json";
const GITHUB_REPO = process.env.GITHUB_REPO || "vn99instrumental-web/vnstock-cron-v2.0";

/** Validate cấu trúc tối thiểu (khớp config/scoring/schema.json). Trả list lỗi. */
function validateConfig(c: unknown): string[] {
  const errs: string[] = [];
  if (typeof c !== "object" || c === null) return ["config phải là object"];
  const cfg = c as Record<string, unknown>;
  if (!cfg.version_label || typeof cfg.version_label !== "string")
    errs.push("thiếu version_label");

  const fw = cfg.factor_weights as Record<string, Record<string, number>> | undefined;
  for (const lens of ["trade", "hold"] as const) {
    if (!fw?.[lens]) {
      errs.push(`thiếu factor_weights.${lens}`);
      continue;
    }
    for (const f of FACTORS) {
      const v = fw[lens][f];
      if (typeof v !== "number" || v < 0 || v > 1)
        errs.push(`factor_weights.${lens}.${f} phải trong [0,1]`);
    }
  }

  const gm = cfg.gate_matrix as Record<string, unknown> | undefined;
  const regimes = gm?.regimes as string[] | undefined;
  if (!Array.isArray(regimes) || regimes.length < 1) errs.push("gate_matrix.regimes rỗng");
  else {
    for (const f of FACTORS) {
      const row = gm?.[f] as number[] | undefined;
      if (!Array.isArray(row) || row.length !== regimes.length)
        errs.push(`gate_matrix.${f} phải có ${regimes.length} phần tử`);
      else if (row.some((x) => typeof x !== "number" || x < 0 || x > 1))
        errs.push(`gate_matrix.${f} có giá trị ngoài [0,1]`);
    }
  }

  const th = cfg.thresholds as unknown[] | undefined;
  if (!Array.isArray(th) || th.length < 2) errs.push("thresholds cần ≥2 mốc");
  return errs;
}

/** Đếm số NHÓM logic thay đổi so với current (one-change-per-cycle). */
function changedGroups(next: ScoringConfig, cur: ScoringConfig | null): string[] {
  if (!cur) return [];
  const groups: (keyof ScoringConfig)[] = ["factor_weights", "gate_matrix", "thresholds", "extras"];
  return groups.filter(
    (g) => JSON.stringify(next[g] ?? null) !== JSON.stringify(cur[g] ?? null),
  );
}

async function githubGetSha(token: string): Promise<{ sha: string; current: ScoringConfig | null }> {
  const url = `https://api.github.com/repos/${GITHUB_REPO}/contents/${CONFIG_PATH}?ref=main`;
  const r = await fetch(url, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
    cache: "no-store",
  });
  if (r.status === 404) return { sha: "", current: null };
  if (!r.ok) throw new Error(`GitHub GET ${r.status}`);
  const j = await r.json();
  let current: ScoringConfig | null = null;
  try {
    current = JSON.parse(Buffer.from(j.content, "base64").toString("utf-8"));
  } catch {
    current = null;
  }
  return { sha: j.sha as string, current };
}

export async function POST(request: Request) {
  // 0) Same-origin guard (CSRF defense-in-depth) — chặn POST chéo site.
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (origin && host && new URL(origin).host !== host) {
    return NextResponse.json({ error: "Cross-origin bị chặn." }, { status: 403 });
  }

  // 1) Auth — chỉ owner.
  const user = await getUser();
  if (!isOwner(user?.email)) {
    return NextResponse.json({ error: "Chỉ owner được promote." }, { status: 403 });
  }

  // 2) Parse + validate.
  let body: { config?: ScoringConfig; note?: string; force?: boolean };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Body JSON không hợp lệ." }, { status: 400 });
  }
  const config = body.config;
  if (!config) return NextResponse.json({ error: "Thiếu 'config'." }, { status: 400 });

  const errs = validateConfig(config);
  if (errs.length) return NextResponse.json({ error: "Config sai schema", details: errs }, { status: 400 });

  // 3) Env server-only.
  const token = process.env.GITHUB_TOKEN;
  const sbUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const svcKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!token || !sbUrl || !svcKey) {
    return NextResponse.json(
      { error: "Server chưa cấu hình GITHUB_TOKEN / SUPABASE_SERVICE_ROLE_KEY." },
      { status: 500 },
    );
  }

  // 4) One-change-per-cycle guard.
  let sha = "";
  let current: ScoringConfig | null = null;
  try {
    ({ sha, current } = await githubGetSha(token));
  } catch (e) {
    return NextResponse.json({ error: "Không đọc được active.json: " + String(e) }, { status: 502 });
  }
  const changed = changedGroups(config, current);
  if (changed.length > 1 && !body.force) {
    return NextResponse.json(
      {
        error: "Vi phạm one-change-per-cycle: đổi >1 nhóm.",
        changed_groups: changed,
        hint: "Gửi lại với force=true nếu cố ý.",
      },
      { status: 409 },
    );
  }

  // 5) Commit active.json vào repo.
  const content = Buffer.from(JSON.stringify(config, null, 2) + "\n", "utf-8").toString("base64");
  const putRes = await fetch(
    `https://api.github.com/repos/${GITHUB_REPO}/contents/${CONFIG_PATH}`,
    {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
      body: JSON.stringify({
        message: `promote[scoring]: ${config.version_label}${body.note ? " — " + body.note : ""}`,
        content,
        branch: "main",
        ...(sha ? { sha } : {}),
      }),
    },
  );
  if (!putRes.ok) {
    const t = await putRes.text();
    return NextResponse.json({ error: `GitHub PUT ${putRes.status}`, detail: t.slice(0, 300) }, { status: 502 });
  }

  // 6) Ghi v4_scoring_configs (service_role): archive production cũ → insert mới.
  const sbHeaders = {
    apikey: svcKey,
    Authorization: `Bearer ${svcKey}`,
    "Content-Type": "application/json",
    Prefer: "return=minimal",
  };
  await fetch(`${sbUrl}/rest/v1/v4_scoring_configs?status=eq.production`, {
    method: "PATCH",
    headers: sbHeaders,
    body: JSON.stringify({ status: "archived" }),
  });
  const insRes = await fetch(`${sbUrl}/rest/v1/v4_scoring_configs`, {
    method: "POST",
    headers: { ...sbHeaders, Prefer: "resolution=merge-duplicates,return=minimal" },
    body: JSON.stringify({
      version_label: config.version_label,
      status: "production",
      factor_weights: config.factor_weights,
      gate_matrix: config.gate_matrix,
      thresholds: config.thresholds,
      extras_cfg: config.extras ?? null,
      notes: body.note ?? null,
      promoted_at: new Date().toISOString(),
    }),
  });
  if (!insRes.ok) {
    const t = await insRes.text();
    // active.json ĐÃ commit; báo rõ để đồng bộ tay row config.
    return NextResponse.json(
      { warning: "active.json đã commit nhưng ghi v4_scoring_configs lỗi.", detail: t.slice(0, 300) },
      { status: 207 },
    );
  }

  return NextResponse.json({ ok: true, version_label: config.version_label, changed_groups: changed });
}
