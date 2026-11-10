"use client";

import { useMemo, useState } from "react";
import type { SsiV418OfflineEvidence, OfflineTickerRow } from "@/lib/ssi-v418-offline";
import { SSI_V418_AUDIT_SOURCE } from "@/lib/ssi-v418-offline";

type Filter = "all" | "foreign_missing" | "history_short" | "ta_pending";
type Sort = "symbol" | "matched_desc" | "foreign_desc" | "history_asc";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "Tất cả" },
  { value: "foreign_missing", label: "Thiếu khối ngoại" },
  { value: "history_short", label: "Thiếu 252 phiên" },
  { value: "ta_pending", label: "TA chưa đủ kiểm tra" },
];
const SORTS: { value: Sort; label: string }[] = [
  { value: "symbol", label: "Mã A–Z" },
  { value: "matched_desc", label: "GT khớp lớn nhất" },
  { value: "foreign_desc", label: "NN ròng lớn nhất" },
  { value: "history_asc", label: "Ít phiên nhất" },
];

function n(value: string | number | null | undefined, digits = 0): string {
  if (value == null || value === "") return "—";
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString("vi-VN", {
    maximumFractionDigits: digits, minimumFractionDigits: 0,
  }) : "—";
}
function bil(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const amount = Number(value);
  return Number.isFinite(amount) ? n(amount / 1_000_000_000, 2) : "—";
}
function sourceStatus(row: OfflineTickerRow): string {
  if (!row.foreign_arithmetic_verified) return "NN thiếu";
  if (!row.has_252_sessions) return "Lịch sử thiếu";
  if (!row.independent_ta_arithmetic_anchor) return "TA chưa đạt";
  return "Nguồn cơ bản đạt";
}
const METRICS = [
  ["Mã thanh khoản", "liquid_cohort", "Mẫu phiên SSI"],
  ["OHLC + Summary", "same_day_ohlc_summary", "Khớp đúng ngày"],
  ["GT khớp trực tiếp", "matched_turnover", "Không dùng close × volume"],
  ["Khối ngoại đủ", "foreign_value_valid", "Thiếu không đổi thành 0"],
  ["Lịch sử ≥252", "history_252", "Ứng viên tính TA"],
  ["Lịch sử ≥400", "history_400", "Ứng viên EMA"],
  ["VN100 staging", "vn100_staged_21day_symbols", "21 phiên, chưa chứng nhận thành viên lịch sử"],
  ["Tín hiệu v4.18", "signal_contract_count", "Mapping, chưa phải điểm"],
] as const;

export function SsiOfflineComparison({ data }: { data: SsiV418OfflineEvidence }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("symbol");
  const rows = useMemo(() => {
    const q = query.trim().toUpperCase();
    return data.rows.filter((row) => (
      (!q || row.symbol.includes(q)) &&
      (filter === "all" ||
        (filter === "foreign_missing" && !row.foreign_arithmetic_verified) ||
        (filter === "history_short" && !row.has_252_sessions) ||
        (filter === "ta_pending" && !row.independent_ta_arithmetic_anchor))
    )).sort((a,b) => {
      if (sort === "matched_desc") return Number(b.ssi_matched_turnover_vnd ?? 0) - Number(a.ssi_matched_turnover_vnd ?? 0);
      if (sort === "foreign_desc") return Number(b.ssi_foreign_net_vnd ?? -Infinity) - Number(a.ssi_foreign_net_vnd ?? -Infinity);
      if (sort === "history_asc") return (a.available_history_sessions ?? 0) - (b.available_history_sessions ?? 0);
      return a.symbol.localeCompare(b.symbol);
    });
  }, [data.rows, query, filter, sort]);
  return (
    <section className="card min-w-0 p-4 sm:p-5" aria-label="Dữ liệu SSI Finhay offline">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--color-muted)]">Thế hệ 6 · SSI V3 + Finhay · Read-only</p>
          <h2 className="mt-1 text-base font-bold">Đối chiếu mức sẵn sàng dữ liệu v4.18</h2>
          <p className="mt-1 max-w-[900px] text-xs leading-relaxed text-[var(--color-muted)]">
            Nguồn SSI phiên <strong>{data.source_trade_date}</strong> · giá OHLC do SSI cung cấp, không điều chỉnh ngược lịch sử ·
            không cập nhật thời gian thực. Dữ liệu này <strong>khác</strong> bridge Gen6 bên trên.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-red-500/40 px-2.5 py-1 text-[11px] font-semibold text-[var(--color-sell)]">NOT FOR TRADING</span>
          <a href={SSI_V418_AUDIT_SOURCE} target="_blank" rel="noreferrer"
             className="rounded-md border border-[var(--color-border)] px-2.5 py-1 text-[11px] font-semibold hover:bg-black/5">
            Báo cáo gốc ↗
          </a>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        {METRICS.map(([label, key, desc]) => (
          <div key={key} className="min-w-0 rounded-lg border border-[var(--color-border)] p-2.5">
            <p className="text-[10px] text-[var(--color-muted)]">{label}</p>
            <p className="tabular mt-1 text-xl font-bold">{n(data.metrics[key])}</p>
            <p className="mt-1 text-[10px] leading-tight text-[var(--color-muted)]">{desc}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
        <div className="rounded-lg border border-[var(--color-border)] p-3">
          <p className="font-semibold">VNINDEX</p><p className="tabular mt-1 text-lg">{n(data.metrics.vnindex_finalized_sessions)} phiên</p>
          <p className="text-[var(--color-muted)]">Lịch sử nguồn trực tiếp</p>
        </div>
        <div className="rounded-lg border border-[var(--color-border)] p-3">
          <p className="font-semibold">Finhay cơ bản</p><p className="tabular mt-1 text-lg">{n(data.metrics.finhay_pe_pb_direct_sample)}/10 P/E, P/B</p>
          <p className="text-[var(--color-muted)]">Tài chính có ngày công bố được kiểm chứng: {n(data.metrics.finhay_pit_certified)}/10</p>
        </div>
        <div className="rounded-lg border border-[var(--color-border)] p-3">
          <p className="font-semibold">TA cơ bản SSI</p><p className="tabular mt-1 text-lg">{n(data.metrics.technical_anchor_candidates)}/{n(data.metrics.liquid_cohort)}</p>
          <p className="text-[var(--color-muted)]">Kiểm tra số học độc lập, không phải parity vnstock_ta</p>
        </div>
      </div>
      <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs leading-relaxed">
        <strong>Chưa thể so điểm BUY/SELL SSI với VNStock:</strong> 0/17 tín hiệu được chứng nhận giá trị tương đương.
        Giá SSI dưới đây là giá báo cáo từ nguồn, không ghép với giá VCI khác ngày; các cột SSI score/decision
        đều <code>null</code>. VN100 chưa có lịch sử thay đổi thành viên được chứng nhận.
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <label htmlFor="ssi-gen6-query" className="sr-only">Tìm mã SSI</label>
        <input id="ssi-gen6-query" type="search" placeholder="Tìm mã…"
          value={query} onChange={(e) => setQuery(e.target.value)}
          className="min-h-9 min-w-[120px] flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs sm:max-w-[200px]" />
        <label htmlFor="ssi-gen6-filter" className="sr-only">Lọc tình trạng</label>
        <select id="ssi-gen6-filter" value={filter} onChange={(e)=>setFilter(e.target.value as Filter)}
          className="min-h-9 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-xs">
          {FILTERS.map(x=><option key={x.value} value={x.value}>{x.label}</option>)}
        </select>
        <label htmlFor="ssi-gen6-sort" className="sr-only">Sắp xếp mã</label>
        <select id="ssi-gen6-sort" value={sort} onChange={(e)=>setSort(e.target.value as Sort)}
          className="min-h-9 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-xs">
          {SORTS.map(x=><option key={x.value} value={x.value}>{x.label}</option>)}
        </select>
        <span className="text-[11px] text-[var(--color-muted)]">{rows.length}/{data.rows.length} mã</span>
      </div>
      <div className="mt-2 max-h-[480px] overflow-auto rounded-lg border border-[var(--color-border)]">
        <table className="w-full min-w-[830px] border-collapse text-left text-xs">
          <thead className="sticky top-0 z-10 bg-[var(--color-surface)] text-[11px] text-[var(--color-muted)]">
            <tr className="border-b border-[var(--color-border)]">
              <th className="px-3 py-2">Mã</th><th className="px-3 py-2 text-right">Close SSI (đ)</th>
              <th className="px-3 py-2 text-right">GT khớp (tỷ)</th><th className="px-3 py-2 text-right">NN ròng (tỷ)</th>
              <th className="px-3 py-2 text-right">Số phiên</th><th className="px-3 py-2">QC nguồn</th><th className="px-3 py-2">So điểm</th>
            </tr>
          </thead>
          <tbody>{rows.map(row => (
            <tr key={row.symbol} className="border-b border-[var(--color-border)]/60 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]">
              <td className="px-3 py-2 font-bold">{row.symbol}</td>
              <td className="tabular px-3 py-2 text-right">{n(row.ssi_close_as_reported_vnd)}</td>
              <td className="tabular px-3 py-2 text-right">{bil(row.ssi_matched_turnover_vnd)}</td>
              <td className="tabular px-3 py-2 text-right">{row.foreign_arithmetic_verified ? bil(row.ssi_foreign_net_vnd) : "Thiếu"}</td>
              <td className="tabular px-3 py-2 text-right">{n(row.available_history_sessions)}</td>
              <td className="px-3 py-2">{sourceStatus(row)}</td>
              <td className="px-3 py-2 text-[var(--color-muted)]">Chưa đủ nguồn</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <details className="mt-4 rounded-lg border border-[var(--color-border)] p-3">
        <summary className="cursor-pointer text-xs font-semibold">17 tín hiệu v4.18 · tình trạng nguồn & công thức (chưa phải điểm)</summary>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {data.signals.map(s=>(
            <div key={s.id} className="min-w-0 rounded-md border border-[var(--color-border)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2 text-xs"><strong className="font-mono">{s.id}</strong><span className="text-[var(--color-muted)]">{s.factor}</span></div>
              <p className="mt-1 break-words font-mono text-[10px] text-[var(--color-muted)]">{s.source_readiness}</p>
              <p className="mt-1 text-[10px] text-[var(--color-sell)]">Chưa xác nhận tương đương</p>
            </div>
          ))}
        </div>
      </details>
      <p className="mt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
        Dữ liệu: SSI repo đã nghiệm thu offline, chỉ chụp một phiên và được nhúng ở bản build web.
        Để cập nhật số liệu phiên mới phải tạo và đồng bộ lại snapshot; không coi số này là realtime.
        Không thay đổi quyết định hoặc dữ liệu production hiện tại.
      </p>
    </section>
  );
}
