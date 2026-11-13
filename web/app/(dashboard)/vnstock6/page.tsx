import { EmptyState, InsightStrip, PageHeader, QueryErrorState } from "@/components/ui";
import { getVnstock6Comparison } from "@/lib/vnstock6-comparison";
import { getVnstock6DashboardManifest } from "@/lib/data-source/vnstock6-serving";
import { getSsiV418OfflineEvidence } from "@/lib/ssi-v418-offline";
import { SsiOfflineComparison } from "@/components/ssi-offline-comparison";
import { getSsiV418Shadow } from "@/lib/ssi-v418-shadow";
import { SsiV418ShadowPanel } from "@/components/ssi-v418-shadow-panel";

function integer(value: number) {
  return new Intl.NumberFormat("vi-VN").format(value);
}

function timestamp(value: string) {
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function ProbePanel({
  title,
  badge,
  source,
  packageName,
  packageVersion,
  oapiVersion,
  rows,
  symbols,
  exchanges,
  fptPresent,
}: {
  title: string;
  badge: string;
  source: string;
  packageName: string;
  packageVersion: string;
  oapiVersion?: string;
  rows: number;
  symbols: number;
  exchanges: string[];
  fptPresent: boolean;
}) {
  return (
    <section className="card min-w-0 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--color-muted)]">{badge}</p>
          <h2 className="mt-1 text-base font-bold">{title}</h2>
        </div>
        <span className="rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[11px] font-semibold">{source}</span>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <dt className="text-[11px] text-[var(--color-muted)]">Package</dt>
          <dd className="mt-0.5 break-all font-mono text-xs">{packageName} {packageVersion}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-[var(--color-muted)]">Open API</dt>
          <dd className="mt-0.5 font-mono text-xs">{oapiVersion ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-[var(--color-muted)]">Dòng tham chiếu</dt>
          <dd className="tabular mt-0.5 text-lg font-semibold">{integer(rows)}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-[var(--color-muted)]">Mã duy nhất</dt>
          <dd className="tabular mt-0.5 text-lg font-semibold">{integer(symbols)}</dd>
        </div>
      </dl>
      <div className="mt-4 border-t border-[var(--color-border)] pt-3 text-xs text-[var(--color-muted)]">
        <p>Sàn/nhóm: {exchanges.length ? exchanges.join(", ") : "API không trả cột sàn"}</p>
        <p className="mt-1">FPT: <span className={fptPresent ? "text-[var(--color-buy)]" : "text-[var(--color-sell)]"}>{fptPresent ? "có" : "không có"}</span></p>
      </div>
    </section>
  );
}

export default async function Vnstock6Page() {
  const ssiOffline = getSsiV418OfflineEvidence();
  const ssiShadow = getSsiV418Shadow();
  let data;
  let dashboard;
  try {
    [data, dashboard] = await Promise.all([
      getVnstock6Comparison(),
      getVnstock6DashboardManifest(),
    ]);
  } catch (error) {
    const missing = error instanceof Error && error.message.includes("HTTP 404");
    return (
      <>
        <PageHeader title="Đối chiếu thế hệ 6" desc="Hai môi trường tách biệt · VCI hiện tại và SSI Open API preview." />
        {ssiShadow ? <SsiV418ShadowPanel data={ssiShadow} /> : <div className="card p-3 text-xs">Scoring Shadow v4.18 chưa có dữ liệu kiểm chứng; không sử dụng điểm thay thế.</div>}
        {ssiOffline ? <SsiOfflineComparison data={ssiOffline} /> : null}
        {missing ? (
          <EmptyState title="Chưa có lần chạy đối chiếu" hint="Chạy workflow “Compare current vnstock with generation 6” trên GitHub Actions để tạo snapshot đầu tiên." />
        ) : (
          <QueryErrorState hint="Không đọc được snapshot đối chiếu từ GitHub. Hãy kiểm tra workflow Gen 6 gần nhất." />
        )}
      </>
    );
  }

  const current = data.current;
  const preview = data.preview;
  const comparison = data.comparison;
  const activeGeneratedAt = dashboard.mode === "native" ? dashboard.generated_at : data.generated_at;
  const activeRunUrl = dashboard.mode === "native" ? dashboard.flow.run_url : data.run.url;
  return (
    <div className="space-y-3">
      <PageHeader
        title="Đối chiếu thế hệ 6"
        desc={`Read-only · dữ liệu ${dashboard.mode} cập nhật ${timestamp(activeGeneratedAt)} · snapshot đối chiếu ${timestamp(data.generated_at)}`}
        actions={(
          <a className="rounded-md border border-[var(--color-border)] px-2.5 py-1 text-[11px] font-semibold hover:bg-black/5 dark:hover:bg-white/5" href={activeRunUrl} target="_blank" rel="noreferrer">
            Xem GitHub run ↗
          </a>
        )}
      />

      {ssiShadow ? <SsiV418ShadowPanel data={ssiShadow} /> : (
        <div className="card border border-amber-500/40 p-3 text-xs">Chưa có bản ghi SSI v4.18 Shadow hợp lệ, điểm chưa được tính.</div>
      )}
      {ssiOffline ? <SsiOfflineComparison data={ssiOffline} /> : (
        <div className="card border border-amber-500/40 p-3 text-xs">Chưa có báo cáo SSI/Finhay offline được kiểm chứng để đối chiếu.</div>
      )}

      <InsightStrip
        className="sm:grid-cols-4"
        metrics={[
          { label: "Mã trùng nhau", value: integer(comparison.overlap_symbols), tone: "positive" },
          { label: "Độ phủ giao", value: `${comparison.jaccard_percent.toLocaleString("vi-VN")}%` },
          { label: "Chỉ có ở hiện tại", value: integer(comparison.only_current_count), tone: comparison.only_current_count ? "warning" : "default" },
          { label: "Chỉ có ở Gen 6", value: integer(comparison.only_preview_count), tone: comparison.only_preview_count ? "warning" : "default" },
        ]}
      />

      <div className="grid gap-3 lg:grid-cols-2">
        <ProbePanel
          title="Pipeline hiện tại"
          badge="Snapshot production"
          source={current.source}
          packageName={current.package}
          packageVersion={current.package_version}
          rows={current.reference.rows}
          symbols={current.reference.unique_symbols}
          exchanges={current.reference.exchanges}
          fptPresent={current.reference.fpt_present}
        />
        <ProbePanel
          title="Thế hệ 6 preview"
          badge="API live preview"
          source={preview.source}
          packageName={preview.package}
          packageVersion={preview.package_version}
          oapiVersion={preview.oapi_version}
          rows={preview.reference.rows}
          symbols={preview.reference.unique_symbols}
          exchanges={preview.reference.exchanges}
          fptPresent={preview.reference.fpt_present}
        />
      </div>

      <section className="card p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--color-muted)]">Dashboard serving</p>
            <h2 className="mt-1 text-sm font-bold">Flow Thế hệ 6</h2>
          </div>
          <span className="rounded-full border border-amber-500/40 bg-amber-500/5 px-2.5 py-1 text-[11px] font-semibold">
            {dashboard.mode === "bridge" ? "Bridge có kiểm soát" : "Native độc lập"}
          </span>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {dashboard.flow.stages.map((stage) => (
            <div key={stage.name} className="rounded-lg border border-[var(--color-border)] px-3 py-2">
              <p className="font-mono text-[11px] font-semibold">{stage.name}</p>
              <p className="mt-1 text-[11px] text-[var(--color-muted)]">
                {stage.status} · {stage.mode}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs leading-relaxed text-[var(--color-muted)]">
          {dashboard.mode === "native"
            ? `Tất cả tab hiện đọc release Gen 6 native độc lập, gồm ${integer(dashboard.symbols.length)} mã SSI.`
            : `Tất cả tab hiện đọc cùng contract bridge: signals/scoring từ GitHub production và lọc theo ${integer(dashboard.symbols.length)} mã SSI.`}
        </p>
      </section>

      <section className="card p-4 sm:p-5">
        <h2 className="text-sm font-bold">Sai khác mẫu</h2>
        <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          <div>
            <p className="font-semibold">Chỉ có ở VCI hiện tại</p>
            <p className="mt-1 break-words font-mono text-[var(--color-muted)]">{comparison.only_current_sample.join(", ") || "Không có"}</p>
          </div>
          <div>
            <p className="font-semibold">Chỉ có ở SSI Gen 6</p>
            <p className="mt-1 break-words font-mono text-[var(--color-muted)]">{comparison.only_preview_sample.join(", ") || "Không có"}</p>
          </div>
        </div>
        <ul className="mt-4 space-y-1 border-t border-[var(--color-border)] pt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
          {data.notes.map((note) => <li key={note}>• {note}</li>)}
        </ul>
      </section>
    </div>
  );
}
