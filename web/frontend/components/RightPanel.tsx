"use client";

import type { ConfigStatus, PlanState } from "@/lib/types";

const SOURCE_NAMES: Record<string, string> = {
  google_ads: "Google Ads",
  ga4: "GA4",
  keyword_planner: "Keyword Planner",
  search_console: "Search Console",
  competitor_intel: "竞品情报",
};

export function RightPanel({
  plan,
  status,
  onOpenConfig,
}: {
  plan: PlanState;
  status: ConfigStatus | null;
  onOpenConfig: () => void;
}) {
  const planRows: { label: string; value: string }[] = [];
  if (plan.keywordCandidates != null) planRows.push({ label: "关键词候选", value: `${plan.keywordCandidates} 词` });
  if (plan.keywordClusters != null)
    planRows.push({
      label: "关键词方案",
      value: `${plan.keywordClusters} 组 / ${plan.keywordTotal} 词 / 负向 ${plan.negativeCount}`,
    });
  if (plan.copyReady != null) planRows.push({ label: "文案", value: plan.copyReady ? "已通过校验" : "需修改" });
  if (plan.assetCount != null) planRows.push({ label: "素材", value: `${plan.assetCount} 张` });
  if (plan.campaignName) planRows.push({ label: "广告系列", value: plan.campaignName });
  if (plan.dailyBudget) planRows.push({ label: "日预算", value: plan.dailyBudget });
  if (plan.submittedMode)
    planRows.push({ label: "提交状态", value: `${plan.submittedMode === "live" ? "已真实落盘" : "已出演练回执"}${plan.committed ? "（真实）" : ""}` });
  if (plan.monitorSeverity) planRows.push({ label: "冷启动", value: plan.monitorSeverity });

  return (
    <aside className="flex h-full flex-col gap-4 overflow-y-auto border-l border-hairline bg-surface p-3.5">
      <div className="overflow-hidden rounded-lg border border-hairline">
        <div className="flex items-center justify-between border-b border-hairline px-3 py-2 text-[12.5px] font-bold">
          当前方案
        </div>
        <div className="flex flex-col gap-2 p-3">
          {planRows.length === 0 ? (
            <div className="text-[12.5px] text-muted">
              这轮会话还没有产出。选词、写文案、审方案后，成果会汇总在这里。
            </div>
          ) : (
            planRows.map((r) => (
              <div key={r.label} className="grid grid-cols-[auto_1fr] items-baseline gap-2 text-[13px]">
                <span className="rounded bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] px-1.5 font-mono text-[10px] tracking-wide text-accentstrong">
                  {r.label}
                </span>
                <span className="text-[12.5px] text-ink2">{r.value}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-hairline">
        <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
          <span className="text-[12.5px] font-bold">配置体检</span>
          <button
            type="button"
            onClick={onOpenConfig}
            title="配置中心：快速填写 .env 并检测连通性"
            aria-label="打开配置中心"
            className="flex h-6 w-6 items-center justify-center rounded-md text-muted hover:bg-surface2 hover:text-ink"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path
                d="M6.6 1.8h2.8l.4 2 1.7.7 1.7-1.1 2 2-1.1 1.7.7 1.7 2 .4v2.8l-2 .4-.7 1.7 1.1 1.7-2 2-1.7-1.1-1.7.7-.4 2H6.6l-.4-2-1.7-.7-1.7 1.1-2-2 1.1-1.7-.7-1.7-2-.4V6.6l2-.4.7-1.7L3.5 2.8l2-2 1.7 1.1 1.7-.7.4-2z"
                stroke="currentColor"
                strokeWidth="1.1"
                strokeLinejoin="round"
              />
              <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3" />
            </svg>
          </button>
        </div>
        <div className="flex flex-col gap-2 p-3">
          {status == null ? (
            <div className="text-[12.5px] text-muted">加载中…</div>
          ) : (
            <>
              {Object.entries(status.sources).map(([key, s]) => (
                <div key={key} className="flex items-center justify-between gap-2 text-[12.5px]">
                  <span className="text-ink2">{SOURCE_NAMES[key] ?? key}</span>
                  {s.credentials_configured ? (
                    <span className="whitespace-nowrap text-[11.5px] text-goodtext">✓ 已配置</span>
                  ) : (
                    <span className="whitespace-nowrap text-[11.5px] text-critical">缺 {s.missing_keys.length} 项凭证</span>
                  )}
                </div>
              ))}
              <div className="flex items-center justify-between gap-2 text-[12.5px]">
                <span className="text-ink2">图像生成</span>
                <span className="whitespace-nowrap text-[11.5px] text-goodtext">
                  ✓ {status.image.effective_mode === "live" ? "真出图" : "已就绪 · 占位图模式"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 text-[12.5px]">
                <span className="text-ink2">账号写入</span>
                <span className="whitespace-nowrap text-[11.5px] text-muted">
                  🔒 {status.ads_write.effective_mode === "live" ? "真实落盘" : "演练模式"} · 开关未开
                </span>
              </div>
              <div className="border-t border-dashed border-hairline pt-2 text-[11px] text-muted">
                只显示键名与状态，凭证值永不显示。点右上角齿轮可快速填写 .env 并检测连通性。
              </div>
            </>
          )}
        </div>
      </div>

      <div className="mt-auto text-center font-mono text-[10.5px] tracking-wide text-muted">
        投放作战室 · 对话式控制台
      </div>
    </aside>
  );
}
