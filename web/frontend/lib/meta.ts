/** 展示层的共享字典：agent 名、指标名、格式化 */

export const AGENT_NAMES: Record<string, string> = {
  digital_marketing_agent: "调度中枢",
  performance_agent: "投放表现分析",
  keyword_agent: "关键词规划",
  creative_agent: "文案与视觉创意",
  strategy_agent: "投放策略与风控",
};

export function agentLabel(name: string): string {
  return AGENT_NAMES[name] ?? name;
}

export type MetricFmt = "num" | "num2" | "pct" | "cny";

export const METRIC_META: Record<string, { label: string; fmt: MetricFmt }> = {
  impressions: { label: "曝光", fmt: "num" },
  clicks: { label: "点击", fmt: "num" },
  cost: { label: "花费", fmt: "cny" },
  conversions: { label: "转化", fmt: "num" },
  ctr_pct: { label: "点击率 CTR", fmt: "pct" },
  cpc: { label: "平均 CPC", fmt: "cny" },
  cvr_pct: { label: "转化率", fmt: "pct" },
  cpa: { label: "单次转化成本 CPA", fmt: "cny" },
  sessions: { label: "会话", fmt: "num" },
  users: { label: "用户", fmt: "num" },
  revenue: { label: "收入", fmt: "cny" },
  aov: { label: "客单价", fmt: "cny" },
  days: { label: "天数", fmt: "num" },
};

export function fmtMetric(value: unknown, fmt: MetricFmt): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  switch (fmt) {
    case "num":
      return n.toLocaleString("zh-CN");
    case "num2":
      return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    case "pct":
      return `${n.toFixed(2)}%`;
    case "cny":
      return `¥${n.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
  }
}

export function fmtNumber(value: unknown): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("zh-CN") : String(value);
}
