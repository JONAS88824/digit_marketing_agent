"use client";

import { Card, DeltaChip, NoteBox, Stat, WarnBox } from "../ui";
import { TrendChart } from "../TrendChart";
import { METRIC_META, fmtMetric } from "@/lib/meta";

type Dict = Record<string, unknown>;

/** get_ads_metrics / get_ga4_metrics：聚合指标一览 */
export function MetricsCard({
  result,
  title,
}: {
  result: Dict;
  title: string;
}) {
  const metrics = (result.metrics ?? {}) as Dict;
  const units = (result.metric_units ?? {}) as Dict;
  const entries = Object.entries(metrics).filter(([k]) => METRIC_META[k]);
  return (
    <Card
      title={title}
      hint={`${String(result.date_from)} ~ ${String(result.date_to)} · ${result.source === "ga4" ? "GA4" : "Google Ads"} · ${result.google_ads_mode === "live" || result.ga4_mode === "live" ? "真实数据" : "演示数据"}`}
    >
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {entries.map(([key, value]) => {
          const meta = METRIC_META[key];
          return (
            <Stat key={key} label={meta.label} value={fmtMetric(value, meta.fmt)} note={(units[key] as string) ?? undefined} />
          );
        })}
      </div>
    </Card>
  );
}

type Comparison = {
  metric: string;
  current: number | null;
  previous: number | null;
  change_pct: number | null;
  verdict: string;
  needs_attention?: boolean;
};

/** compare_ads_metrics / compare_ga4_metrics：环比 KPI 行 */
export function CompareCard({
  result,
  title,
}: {
  result: Dict;
  title: string;
}) {
  const comparisons = (result.comparisons ?? []) as Comparison[];
  const attention = (result.attention_metrics ?? []) as string[];
  return (
    <div className="flex flex-col gap-2.5">
      <Card title={title} hint={`本期 ${String(result.current_period)} vs 上期 ${String(result.previous_period)}`}>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {comparisons.map((c) => {
            const meta = METRIC_META[c.metric];
            return (
              <Stat
                key={c.metric}
                label={meta?.label ?? c.metric}
                value={fmtMetric(c.current, meta?.fmt ?? "num")}
                note={`上期 ${fmtMetric(c.previous, meta?.fmt ?? "num")}`}
              >
                <DeltaChip changePct={c.change_pct} verdict={c.verdict} />
              </Stat>
            );
          })}
        </div>
      </Card>
      {attention.length > 0 ? (
        <WarnBox>
          <b>需要关注：</b>
          {attention.map((m) => METRIC_META[m]?.label ?? m).join("、")}明显恶化，建议看逐日趋势定位从哪天开始。
        </WarnBox>
      ) : null}
      {result.hint ? <NoteBox>{String(result.hint)}</NoteBox> : null}
    </div>
  );
}

/** get_daily_trend：逐日趋势折线图 */
export function DailyTrendCard({ result }: { result: Dict }) {
  const series = (result.series ?? []) as { day: string; value: number | null }[];
  const metricLabel: Record<string, string> = {
    ctr: "点击率 CTR（%）",
    cpc: "平均 CPC（元）",
    cvr: "转化率（%）",
    clicks: "点击",
    cost: "花费（元）",
    conversions: "转化",
    impressions: "曝光",
  };
  return (
    <Card
      title={`逐日趋势 · ${metricLabel[result.metric as string] ?? result.metric}`}
      hint={`${String(result.date_from)} ~ ${String(result.date_to)} · ${result.campaign ?? ""} · ${result.source === "ga4" ? "GA4" : "Google Ads"}`}
    >
      <TrendChart points={series} unit={result.unit as string} />
    </Card>
  );
}
