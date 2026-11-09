import Link from "next/link";
import { getVnstock6DashboardManifest } from "@/lib/data-source/vnstock6-serving";

export async function Vnstock6SourceNotice() {
  try {
    const manifest = await getVnstock6DashboardManifest();
    const bridge = manifest.mode === "bridge";
    return (
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/35 bg-amber-500/5 px-3 py-2 text-xs">
        <div>
          <span className="font-semibold text-[var(--color-ink)]">Thế hệ 6 · SSI · {manifest.package_version}</span>
          <span className="ml-2 text-[var(--color-muted)]">
            {bridge
              ? "Bridge đối chiếu: dùng scoring GitHub hiện tại, lọc theo universe SSI. Chưa phải pipeline Gen 6 native."
              : "Pipeline Gen 6 native độc lập."}
          </span>
        </div>
        <Link href="/vnstock6" className="font-semibold text-[var(--color-accent)] hover:underline">
          Trạng thái flow
        </Link>
      </div>
    );
  } catch {
    return (
      <div className="mb-3 rounded-lg border border-red-500/35 bg-red-500/5 px-3 py-2 text-xs text-[var(--color-muted)]">
        Nguồn Thế hệ 6 đang được chọn nhưng manifest chưa khả dụng. Không fallback sang Supabase hoặc GitHub.
      </div>
    );
  }
}