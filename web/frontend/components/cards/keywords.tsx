"use client";

import { Card, Chip, MiniTable, NoteBox, Stat, WarnBox } from "../ui";
import { fmtNumber } from "@/lib/meta";

type Dict = Record<string, unknown>;

function competitionChip(competition: string) {
  const v = competition === "LOW" ? "pass" : competition === "HIGH" ? "fail" : "warn";
  const label = competition === "LOW" ? "低" : competition === "HIGH" ? "高" : "中";
  return <Chip variant={v as "pass" | "fail" | "warn"}>{label}</Chip>;
}

function trendChip(direction: unknown, changePct: unknown) {
  if (direction === "rising") {
    return <Chip variant="up">在涨{changePct != null ? ` ${Number(changePct).toFixed(0)}%` : ""}</Chip>;
  }
  if (direction === "falling") {
    return <Chip variant="fail">在跌{changePct != null ? ` ${Number(changePct).toFixed(0)}%` : ""}</Chip>;
  }
  return <Chip variant="default">平稳</Chip>;
}

/** plan_keywords：候选词表 */
export function KeywordPlanCard({ result }: { result: Dict }) {
  const keywords = (result.keywords ?? []) as Dict[];
  return (
    <Card
      title={`关键词候选 · ${String(result.total_matched)} 词匹配，展示 ${String(result.returned)} 个`}
      hint={`${String(result.industry)} / ${String(result.product)} · Keyword Planner 口径 · 演示词库`}
    >
      <MiniTable
        maxHeight={360}
        columns={[
          { key: "k", header: "关键词", render: (r) => <span className="font-semibold">{String(r.keyword)}</span> },
          { key: "intent", header: "意图", render: (r) => <Chip variant="default">{String(r.intent)}</Chip> },
          { key: "vol", header: "月搜索量", align: "right", render: (r) => fmtNumber(r.avg_monthly_searches) },
          { key: "comp", header: "竞争", render: (r) => competitionChip(String(r.competition)) },
          { key: "cpc", header: "预估 CPC", align: "right", render: (r) => `¥${Number(r.avg_cpc).toFixed(2)}` },
          {
            key: "bid",
            header: "首页出价区间",
            align: "right",
            render: (r) => {
              const range = r.top_of_page_bid_range as [number, number] | undefined;
              return range ? `¥${range[0].toFixed(2)} ~ ${range[1].toFixed(2)}` : "—";
            },
          },
        ]}
        rows={keywords}
      />
      {result.truncated ? (
        <div className="mt-2 text-[11.5px] text-muted">结果过多已截断，缩小范围或分意图查询可以看到其余词。</div>
      ) : null}
    </Card>
  );
}

/** forecast_keywords：成本预估 + 逐词趋势 */
export function ForecastCard({ result }: { result: Dict }) {
  const f = (result.cost_forecast ?? {}) as Dict;
  const assumptions = (f.assumptions ?? {}) as Dict;
  const trends = (result.per_keyword_trend ?? []) as Dict[];
  return (
    <div className="flex flex-col gap-2.5">
      <Card title="投放成本预估" hint={`${String(f.keyword_count)} 个词 · 月度`}>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Stat label="月搜索量合计" value={fmtNumber(f.monthly_searches)} />
            <Stat label="预计月点击" value={fmtNumber(f.estimated_monthly_clicks)} />
            <Stat label="预计月花费" value={`¥${fmtNumber(f.estimated_monthly_cost)}`} />
            <Stat label="预计均价 CPC" value={`¥${Number(f.estimated_avg_cpc).toFixed(2)}`} />
          </div>
          {assumptions.warning ? <WarnBox>{String(assumptions.warning)}</WarnBox> : null}
        </div>
      </Card>
      {trends.length > 0 ? (
        <Card title="逐词趋势" hint="旺季与季节性来自 12 个月搜索量序列">
          <MiniTable
            maxHeight={280}
            columns={[
              { key: "k", header: "关键词", render: (r) => <span className="font-semibold">{String(r.keyword)}</span> },
              { key: "vol", header: "月搜索量", align: "right", render: (r) => fmtNumber(r.avg_monthly_searches) },
              { key: "cpc", header: "均价 CPC", align: "right", render: (r) => `¥${Number(r.avg_cpc).toFixed(2)}` },
              { key: "trend", header: "趋势", render: (r) => trendChip(r.direction, r.change_pct) },
              {
                key: "peak",
                header: "旺季",
                render: (r) => (r.peak_month ? `${String(r.peak_month).slice(5)} 月 · ${Number(r.seasonality_ratio).toFixed(1)}×` : "—"),
              },
            ]}
            rows={trends}
          />
        </Card>
      ) : null}
      {result.hint ? <NoteBox>{String(result.hint)}</NoteBox> : null}
    </div>
  );
}

/** get_competitor_keywords：竞品重仓词 + 缺口分析 */
export function CompetitorCard({ result }: { result: Dict }) {
  const top = (result.top_keywords ?? []) as Dict[];
  const gap = result.gap_analysis as Dict | undefined;
  return (
    <div className="flex flex-col gap-2.5">
      <Card title={`竞品「${String(result.competitor)}」重仓词 · ${String(result.total_keywords)} 个`} hint="第三方估算数据，只能判方向 · 演示数据">
        <MiniTable
          maxHeight={320}
          columns={[
            { key: "k", header: "关键词", render: (r) => <span className="font-semibold">{String(r.keyword)}</span> },
            { key: "pos", header: "预估排名", align: "right", render: (r) => fmtNumber(r.estimated_position) },
            { key: "vis", header: "可见度", align: "right", render: (r) => `${Number(r.visibility_pct).toFixed(1)}%` },
            { key: "cpc", header: "预估 CPC", align: "right", render: (r) => `¥${Number(r.estimated_cpc).toFixed(2)}` },
          ]}
          rows={top}
        />
      </Card>
      {gap ? (
        <Card title="与我方词表的缺口分析" hint={`我方覆盖率 ${Number(gap.my_coverage_pct).toFixed(1)}%`}>
          <div className="flex flex-col gap-2 text-[13px]">
            <div>
              <span className="mb-1 block text-[11.5px] font-semibold text-muted">都在投（正面竞争）</span>
              <div className="flex flex-wrap gap-1.5">
                {((gap.both_bidding ?? []) as string[]).length ? (
                  (gap.both_bidding as string[]).map((k) => (
                    <Chip key={k} variant="default">{k}</Chip>
                  ))
                ) : (
                  <span className="text-muted">无</span>
                )}
              </div>
            </div>
            <div>
              <span className="mb-1 block text-[11.5px] font-semibold text-muted">只有我投（守住的阵地）</span>
              <div className="flex flex-wrap gap-1.5">
                {(gap.only_i_bid as string[]).length ? (
                  (gap.only_i_bid as string[]).map((k) => (
                    <Chip key={k} variant="pass">{k}</Chip>
                  ))
                ) : (
                  <span className="text-muted">无</span>
                )}
              </div>
            </div>
            <div>
              <span className="mb-1 block text-[11.5px] font-semibold text-muted">只有它投（机会缺口）</span>
              <div className="flex flex-wrap gap-1.5">
                {(gap.only_competitor_bids as string[]).length ? (
                  (gap.only_competitor_bids as string[]).map((k) => (
                    <Chip key={k} variant="accent">{k}</Chip>
                  ))
                ) : (
                  <span className="text-muted">无</span>
                )}
              </div>
            </div>
          </div>
        </Card>
      ) : null}
      {result.data_caveat ? <div className="text-[11.5px] text-muted">{String(result.data_caveat)}</div> : null}
    </div>
  );
}

/** get_seo_queries：Search Console 自然搜索词 */
export function SeoQueriesCard({ result }: { result: Dict }) {
  const queries = (result.queries ?? []) as Dict[];
  return (
    <Card title={`SEO 词库 · ${String(result.total_matched)} 个自然搜索词`} hint="Search Console · 数据有 2~3 天延迟 · 演示数据">
      <MiniTable
        maxHeight={320}
        columns={[
          { key: "q", header: "搜索词", render: (r) => <span className="font-semibold">{String(r.query)}</span> },
          { key: "clicks", header: "点击", align: "right", render: (r) => fmtNumber(r.clicks) },
          { key: "imp", header: "曝光", align: "right", render: (r) => fmtNumber(r.impressions) },
          { key: "ctr", header: "点击率", align: "right", render: (r) => `${Number(r.ctr_pct).toFixed(2)}%` },
          { key: "pos", header: "平均排名", align: "right", render: (r) => Number(r.position).toFixed(1) },
        ]}
        rows={queries}
      />
      {result.data_caveat ? <div className="mt-2 text-[11.5px] text-muted">{String(result.data_caveat)}</div> : null}
    </Card>
  );
}

/** get_converting_search_terms：GA4 真实转化词 */
export function ConvertingTermsCard({ result }: { result: Dict }) {
  const terms = (result.terms ?? []) as Dict[];
  return (
    <Card
      title={`真实转化搜索词 · ${String(result.total_matched)} 个 · 共 ${String(result.total_conversions)} 次转化`}
      hint={`GA4 转化归因 · 收入 ¥${fmtNumber(result.total_revenue)} · 演示数据`}
    >
      <MiniTable
        maxHeight={320}
        columns={[
          { key: "t", header: "搜索词", render: (r) => <span className="font-semibold">{String(r.term)}</span> },
          { key: "s", header: "会话", align: "right", render: (r) => fmtNumber(r.sessions) },
          { key: "c", header: "转化", align: "right", render: (r) => fmtNumber(r.conversions) },
          { key: "rev", header: "收入", align: "right", render: (r) => `¥${fmtNumber(r.revenue)}` },
          { key: "cvr", header: "转化率", align: "right", render: (r) => (r.cvr_pct != null ? `${Number(r.cvr_pct).toFixed(2)}%` : "—") },
        ]}
        rows={terms}
      />
    </Card>
  );
}

/** record_keyword_plan：方案存档回执 */
export function KeywordPlanSavedCard({ result }: { result: Dict }) {
  const duplicates = (result.cross_group_duplicates ?? []) as Dict[];
  const contradictions = (result.contradictions ?? []) as string[];
  const warnings = (result.warnings ?? []) as string[];
  return (
    <div className="flex flex-col gap-2.5">
      <Card title="关键词方案已存档" hint="后续写文案、审查上线时直接引用">
        <div className="grid grid-cols-3 gap-2.5">
          <Stat label="分组数" value={String(result.cluster_count)} />
          <Stat label="关键词总数" value={String(result.total_keywords)} />
          <Stat label="负向词" value={String(result.negative_count)} />
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries((result.cluster_sizes ?? {}) as Record<string, number>).map(([name, n]) => (
            <Chip key={name} variant="accent">
              {name} · {n} 词
            </Chip>
          ))}
        </div>
      </Card>
      {duplicates.length > 0 ? (
        <WarnBox>
          跨组重复：{duplicates.map((d) => `「${d.keyword}」同时出现在 ${((d.groups as string[]) ?? []).join("、")}`).join("；")}。建议只保留一组，避免自己和自己竞价。
        </WarnBox>
      ) : null}
      {contradictions.length > 0 ? <WarnBox>自相矛盾（已拦截）：{contradictions.join("；")}</WarnBox> : null}
      {warnings.length > 0 ? <NoteBox>{warnings.join("；")}</NoteBox> : null}
    </div>
  );
}
