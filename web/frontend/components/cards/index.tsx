"use client";

import { MetricsCard, CompareCard, DailyTrendCard } from "./performance";
import {
  KeywordPlanCard,
  ForecastCard,
  CompetitorCard,
  SeoQueriesCard,
  ConvertingTermsCard,
  KeywordPlanSavedCard,
} from "./keywords";
import { UspCard, AdCopyCard, VisualAssetsCard, InspectAssetCard } from "./creative";
import {
  BudgetReviewCard,
  ComplianceCard,
  AssembleCard,
  ReceiptCard,
  MonitorCard,
} from "./strategy";

type Dict = Record<string, unknown>;

function GenericCard({ name, result }: { name: string; result: Dict }) {
  const error = result.error_message ?? result.status === "error";
  return (
    <div className="overflow-hidden rounded-lg border border-hairline bg-surface">
      <div className="flex items-center gap-2 border-b border-hairline px-3.5 py-2 text-[13px] font-bold">
        {error ? <span className="text-critical">工具出错 · {name}</span> : name}
        {result.status ? <Chip>{String(result.status)}</Chip> : null}
      </div>
      <details className="px-3.5 py-2">
        <summary className="cursor-pointer text-[12.5px] text-muted">查看原始返回</summary>
        <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-surface2 p-2.5 font-mono text-[11px] leading-relaxed text-ink2">
          {JSON.stringify(result, null, 2)}
        </pre>
      </details>
      {result.error_message ? (
        <div className="px-3.5 pb-2.5 text-[12.5px] text-critical">{String(result.error_message)}</div>
      ) : null}
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-hairline bg-surface2 px-2 py-px text-[11px] font-semibold text-ink2">
      {children}
    </span>
  );
}

/** 工具名 → 卡片组件的分发表。
 *
 * 有专门设计的工具渲染成结构化卡片；
 * 没设计的（范围查询、上下文工具等）走通用 JSON 折叠卡。
 */
export function ToolCard({
  name,
  result,
  sessionId,
}: {
  name: string;
  result: unknown;
  sessionId: string;
}) {
  const r = (result ?? {}) as Dict;
  switch (name) {
    case "get_ads_metrics":
      return <MetricsCard result={r} title="Google Ads 聚合表现" />;
    case "get_ga4_metrics":
      return <MetricsCard result={r} title="GA4 站内表现" />;
    case "compare_ads_metrics":
      return <CompareCard result={r} title="Google Ads 环比" />;
    case "compare_ga4_metrics":
      return <CompareCard result={r} title="GA4 环比" />;
    case "get_daily_trend":
      return <DailyTrendCard result={r} />;
    case "plan_keywords":
      return <KeywordPlanCard result={r} />;
    case "forecast_keywords":
      return <ForecastCard result={r} />;
    case "get_competitor_keywords":
      return <CompetitorCard result={r} />;
    case "get_seo_queries":
      return <SeoQueriesCard result={r} />;
    case "get_converting_search_terms":
      return <ConvertingTermsCard result={r} />;
    case "record_keyword_plan":
      return <KeywordPlanSavedCard result={r} />;
    case "get_product_usps":
      return <UspCard result={r} />;
    case "validate_ad_copy":
      return <AdCopyCard result={r} />;
    case "render_visual_assets":
      return <VisualAssetsCard result={r} />;
    case "inspect_visual_asset":
      return <InspectAssetCard result={r} sessionId={sessionId} />;
    case "review_budget_and_bidding":
      return <BudgetReviewCard result={r} />;
    case "screen_policy_compliance":
      return <ComplianceCard result={r} />;
    case "assemble_campaign_payload":
      return <AssembleCard result={r} />;
    case "submit_campaign_payload":
      return <ReceiptCard result={r} action="提交方案到 Google Ads · 回执" />;
    case "pause_campaign":
      return <ReceiptCard result={r} action="暂停广告系列 · 回执" />;
    case "monitor_new_campaign":
      return <MonitorCard result={r} />;
    default:
      return <GenericCard name={name} result={r} />;
  }
}
