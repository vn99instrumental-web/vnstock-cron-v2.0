"use client";

import { useMemo, useState } from "react";
import type { V418ShadowDataset, V418ShadowRow, V418ShadowSignal } from "@/lib/ssi-v418-shadow";
import { V418_SHADOW_SOURCE_URL } from "@/lib/ssi-v418-shadow";

type Filter = "all" | "has_candidates" | "no_candidates" | "missing_finance" | "missing_flow";
type Sort = "symbol" | "candidates_desc" | "missing_desc" | "trade_contribution_desc";

const FINANCE = new Set(["fund_core","growth_core","cf_core","mkt_context"]);
const FLOW = new Set(["of_phasefix","depth_wall","prop_5d","insider"]);
const FACTOR_LABELS: Record<string,string> = {
  mean_reversion: "Hồi phục",
  breakout: "Xu hướng",
  flow: "Dòng tiền",
  fundamental: "Cơ bản",
  growth: "Tăng trưởng",
  context: "Bối cảnh",
};

function fmt(n: number | null | undefined, digits=2): string {
  return n == null || !Number.isFinite(n) ? "—" : n.toLocaleString("vi-VN", {
    minimumFractionDigits:0, maximumFractionDigits: digits,
  });
}

function partialValue(row: V418ShadowRow, horizon: "trade" | "hold"): number | null {
  return row.scenario_sideways[horizon]?.known_core_contribution_only ?? null;
}

function missing(row: V418ShadowRow, ids: Set<string>): boolean {
  return row.signals.some(s=>ids.has(s.id) && s.candidate_points === null);
}

function Detail({ row }: { row: V418ShadowRow }) {
  const trade=row.scenario_sideways.trade;
  const hold=row.scenario_sideways.hold;
  return (
    <div className="space-y-3 py-3 text-xs">
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 leading-relaxed">
        <strong>{row.symbol} — chưa được chấm điểm chính thức.</strong>{" "}
        Chỉ hiển thị tín hiệu nguồn ứng viên; phần đóng góp bên dưới sử dụng
        <strong> giả định thị trường SIDEWAYS</strong>, KHÔNG phải regime thực tế.
        Factor chưa đủ nguồn, điểm thưởng và tín hiệu thiếu không được thay bằng 0;
        không cộng số dưới đây thành score_trade hoặc BUY/SELL.
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        {(["trade","hold"] as const).map(horizon=>{
          const block=horizon==="trade"?trade:hold;
          return (
            <div key={horizon} className="rounded-lg border border-[var(--color-border)] p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-semibold">{horizon==="trade"?"TRADE":"HOLD"} · Đóng góp thành phần đã quan sát</p>
                  <p className="mt-1 text-[11px] text-[var(--color-muted)]">SIDEWAYS giả định · cap và weight v4.18 gốc</p>
                </div>
                <span className="font-mono text-sm font-bold">{fmt(block?.known_core_contribution_only)}*</span>
              </div>
              {block ? (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {Object.entries(block.factor_partial_contributions).map(([factor,value])=>(
                    <div key={factor} className="rounded-md bg-black/[0.03] px-2 py-1.5 dark:bg-white/[0.04]">
                      <span className="text-[11px] text-[var(--color-muted)]">{FACTOR_LABELS[factor]||factor}</span>
                      <span className="ml-2 font-mono font-semibold">{value>0?"+":""}{fmt(value)}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="mt-2 text-[var(--color-muted)]">Chưa có tín hiệu đủ điều kiện tính thành phần.</p>}
              <p className="mt-2 text-[10px] text-[var(--color-muted)]">
                *Không phải tổng điểm. Factor thiếu hoặc chưa đủ tín hiệu: {block?.missing_factor_names.map(x=>FACTOR_LABELS[x]||x).join(", ")||"—"}.
              </p>
            </div>
          );
        })}
      </div>
      <div className="rounded-lg border border-[var(--color-border)] p-3">
        <div className="flex flex-wrap items-center justify-between gap-1">
          <strong>17 tín hiệu · trạng thái từng đầu vào</strong>
          <span className="text-[11px] text-[var(--color-muted)]">
            {row.candidate_signal_count} có ứng viên / {row.missing_signal_count} thiếu · 0 được chứng nhận parity
          </span>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {row.signals.map((s: V418ShadowSignal)=>(
            <div key={s.id} className="min-w-0 rounded-md border border-[var(--color-border)] px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <strong className="font-mono text-[11px]">{s.id}</strong>
                <span className={s.candidate_points!==null
                  ? "text-[11px] font-semibold text-[var(--color-buy)]"
                  : "text-[11px] font-semibold text-[var(--color-sell)]"}>
                  {s.candidate_points!==null?("Ứng viên "+(s.candidate_points>0?"+":"")+s.candidate_points):"CHƯA CÓ"}
                </span>
              </div>
              <p className="mt-1 text-[10px] text-[var(--color-muted)]">{FACTOR_LABELS[s.factor]||s.factor} · biên ±{s.span}</p>
              {s.candidate_points===null && (
                <p className="mt-1 break-words text-[10px] text-[var(--color-muted)]">
                  {s.missing_reason ?? "Nguồn hoặc công thức chưa đủ kiểm chứng"}
                </p>
              )}
              {s.candidate_points!==null && (
                <p className="mt-1 text-[10px] text-[var(--color-muted)]">
                  Chưa chứng nhận cùng đầu vào/phương pháp v4.18
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Read-only source exhibit; never infer a decision or missing factor value. */
export function SsiV418ShadowPanel({ data }: { data: V418ShadowDataset }) {
  const [query,setQuery]=useState("");
  const [filter,setFilter]=useState<Filter>("all");
  const [sort,setSort]=useState<Sort>("candidates_desc");
  const [selected,setSelected]=useState<string | null>(null);
  const rows=useMemo(()=>{
    const q=query.trim().toUpperCase();
    return data.rows.filter(row=>(
      (!q || row.symbol.includes(q)) &&
      (filter==="all" ||
       (filter==="has_candidates" && row.candidate_signal_count>0) ||
       (filter==="no_candidates" && row.candidate_signal_count===0) ||
       (filter==="missing_finance" && missing(row,FINANCE)) ||
       (filter==="missing_flow" && missing(row,FLOW)))
    )).sort((a,b)=>{
      if(sort==="candidates_desc") return b.candidate_signal_count-a.candidate_signal_count || a.symbol.localeCompare(b.symbol);
      if(sort==="missing_desc") return b.missing_signal_count-a.missing_signal_count || a.symbol.localeCompare(b.symbol);
      if(sort==="trade_contribution_desc") return (partialValue(b,"trade")??-Infinity)-(partialValue(a,"trade")??-Infinity);
      return a.symbol.localeCompare(b.symbol);
    });
  },[data.rows,filter,query,sort]);

  return (
    <section className="card min-w-0 p-4 sm:p-5" aria-label="Scoring Shadow SSI Finhay v4.18">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--color-muted)]">
            Thế hệ 6 · v4.18 · Scoring Shadow
          </p>
          <h2 className="mt-1 text-base font-bold">Điểm thành phần v4.18 từ SSI + Finhay</h2>
          <p className="mt-1 max-w-[920px] text-xs leading-relaxed text-[var(--color-muted)]">
            Nguồn thực phiên <strong>{data.source_trade_date}</strong>. Chỉ tín hiệu có dữ liệu ứng viên mới
            được đưa vào <strong>phép tính đóng góp thành phần theo kịch bản giả định SIDEWAYS</strong>;
            các tín hiệu thiếu giữ <code>null</code>. Không phải điểm Trade/Hold hoàn chỉnh.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-md border border-amber-500/40 px-2 py-1 text-[11px] font-semibold">
            SOURCE SHADOW
          </span>
          <span className="rounded-md border border-red-500/40 px-2 py-1 text-[11px] font-semibold text-[var(--color-sell)]">
            NOT FOR TRADING
          </span>
          <a className="rounded-md border border-[var(--color-border)] px-2 py-1 text-[11px] font-semibold hover:bg-black/5"
            href={V418_SHADOW_SOURCE_URL} target="_blank" rel="noreferrer">JSON nguồn ↗</a>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-5">
        <div className="rounded-md border border-[var(--color-border)] p-3"><p className="text-[11px] text-[var(--color-muted)]">Mã đã đối chiếu</p><p className="mt-1 text-xl font-bold">{data.summary.cohort_symbols}</p></div>
        <div className="rounded-md border border-[var(--color-border)] p-3"><p className="text-[11px] text-[var(--color-muted)]">Có 9/17 tín hiệu ứng viên</p><p className="mt-1 text-xl font-bold">{data.summary.candidate_signal_distribution["9"]??0}</p></div>
        <div className="rounded-md border border-[var(--color-border)] p-3"><p className="text-[11px] text-[var(--color-muted)]">Có 8/17 tín hiệu ứng viên</p><p className="mt-1 text-xl font-bold">{data.summary.candidate_signal_distribution["8"]??0}</p></div>
        <div className="rounded-md border border-[var(--color-border)] p-3"><p className="text-[11px] text-[var(--color-muted)]">Chưa có ứng viên</p><p className="mt-1 text-xl font-bold">{data.summary.candidate_signal_distribution["0"]??0}</p></div>
        <div className="rounded-md border border-[var(--color-border)] p-3"><p className="text-[11px] text-[var(--color-muted)]">Điểm chính thức / BUY/SELL</p><p className="mt-1 text-xl font-bold">0</p></div>
      </div>
      <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs leading-relaxed">
        <strong>Quy tắc tính:</strong> mỗi điểm ứng viên đóng góp theo trọng số, gate và trần factor của engine gốc v4.18;
        chỉ có giá trị ứng viên mới được cộng vào phần đã quan sát. <strong>Không bù hoặc phân bổ lại điểm của tín hiệu thiếu.</strong>{" "}
        Market regime và extras chưa kiểm chứng nên không phát hành tổng điểm hoặc nhãn BUY/SELL.
        Số hiển thị dưới kịch bản SIDEWAYS chỉ để soát công thức; không được dùng làm quyết định giao dịch.
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="v418-shadow-query">Tìm mã</label>
        <input id="v418-shadow-query" type="search" placeholder="Tìm mã…"
          value={query} onChange={e=>setQuery(e.target.value)}
          className="min-h-9 min-w-[100px] flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs sm:max-w-[180px]"/>
        <label className="sr-only" htmlFor="v418-shadow-filter">Lọc trạng thái</label>
        <select id="v418-shadow-filter" value={filter} onChange={e=>setFilter(e.target.value as Filter)}
          className="min-h-9 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-xs">
          <option value="all">Tất cả</option>
          <option value="has_candidates">Có tín hiệu ứng viên</option>
          <option value="no_candidates">Chưa có ứng viên</option>
          <option value="missing_finance">Thiếu tài chính</option>
          <option value="missing_flow">Thiếu dòng tiền/lệnh</option>
        </select>
        <label className="sr-only" htmlFor="v418-shadow-sort">Sắp xếp</label>
        <select id="v418-shadow-sort" value={sort} onChange={e=>setSort(e.target.value as Sort)}
          className="min-h-9 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-xs">
          <option value="candidates_desc">Tín hiệu có nhiều nhất</option>
          <option value="missing_desc">Thiếu nhiều nhất</option>
          <option value="trade_contribution_desc">Đóng góp Trade (giả định)</option>
          <option value="symbol">Mã A–Z</option>
        </select>
        <span className="text-[11px] text-[var(--color-muted)]">{rows.length}/{data.rows.length} mã</span>
      </div>
      <div className="mt-2 max-h-[490px] overflow-auto rounded-lg border border-[var(--color-border)]">
        <table className="w-full min-w-[820px] border-collapse text-left text-xs">
          <thead className="sticky top-0 z-10 bg-[var(--color-surface)] text-[11px] text-[var(--color-muted)]">
            <tr className="border-b border-[var(--color-border)]">
              <th className="px-3 py-2">Mã</th>
              <th className="px-3 py-2 text-right">Ứng viên / 17</th>
              <th className="px-3 py-2 text-right">Trade đóng góp*</th>
              <th className="px-3 py-2 text-right">Hold đóng góp*</th>
              <th className="px-3 py-2">Chỉ báo thiếu</th>
              <th className="px-3 py-2">Score chính thức</th>
              <th className="px-3 py-2">Chi tiết</th>
            </tr>
          </thead>
          <tbody>{rows.map(row=>(
            <tr key={row.symbol} className="border-b border-[var(--color-border)]/60 hover:bg-black/[0.03] dark:hover:bg-white/[0.03]">
              <td className="px-3 py-2 font-bold">{row.symbol}</td>
              <td className="tabular px-3 py-2 text-right">{row.candidate_signal_count}/17</td>
              <td className="tabular px-3 py-2 text-right font-mono">{fmt(partialValue(row,"trade"))}</td>
              <td className="tabular px-3 py-2 text-right font-mono">{fmt(partialValue(row,"hold"))}</td>
              <td className="max-w-[220px] px-3 py-2">
                <span className="font-semibold text-[var(--color-sell)]">{row.missing_signal_count} thiếu</span>
                <p className="mt-0.5 truncate text-[10px] text-[var(--color-muted)]"
                   title={row.signals.filter(s=>s.candidate_points===null).map(s=>s.id).join(", ")}>
                  {row.signals.filter(s=>s.candidate_points===null).map(s=>s.id).join(", ")||"—"}
                </p>
              </td>
              <td className="px-3 py-2 text-[var(--color-muted)]">— (khóa)</td>
              <td className="px-3 py-2">
                <button type="button" onClick={()=>setSelected(x=>x===row.symbol?null:row.symbol)}
                  className="rounded border border-[var(--color-border)] px-2 py-1 text-[11px] font-semibold hover:bg-black/5">
                  {selected===row.symbol?"Đóng":"17 tín hiệu"}
                </button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {selected && data.rows.some(r=>r.symbol===selected) && (
        <div className="mt-3" aria-label="Chi tiết chấm điểm v4.18">
          <Detail row={data.rows.find(r=>r.symbol===selected)!}/>
        </div>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-[var(--color-muted)]">
        *Số đóng góp Trade/Hold hiển thị chỉ là tổng các điểm thành phần đã quan sát trong kịch bản SIDEWAYS giả định,
        KHÔNG phải score_trade hoặc score_hold. Dữ liệu nguồn 09/11/2026, chưa phải realtime.
        Khi có dữ liệu mới cần đồng bộ lại dataset đã được kiểm chứng, không giả mạo ngày hay điểm.
      </p>
    </section>
  );
}
