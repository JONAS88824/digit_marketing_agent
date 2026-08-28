import type { Item, PlanState } from "./types";

/** 从对话里的工具返回值提取"当前方案"面板的状态。
 *
 * 右栏不是又一个数据源——它只是把这轮会话里专员们产出的成果
 * （词表、文案、素材、方案、回执）聚合成一张卡片。
 */
export function derivePlan(items: Item[]): PlanState {
  const plan: PlanState = {};
  for (const item of items) {
    if (item.kind !== "tool" || item.result == null) continue;
    const r = item.result as Record<string, unknown>;
    switch (item.name) {
      case "plan_keywords":
        if (r.status === "success") plan.keywordCandidates = r.returned as number;
        break;
      case "record_keyword_plan":
        if (r.status === "success" || r.status === "warning") {
          plan.keywordClusters = r.cluster_count as number;
          plan.keywordTotal = r.total_keywords as number;
          plan.negativeCount = r.negative_count as number;
        }
        break;
      case "validate_ad_copy":
        if (r.status === "success" || r.status === "needs_fix") {
          plan.copyReady = r.ready_to_submit as boolean;
        }
        break;
      case "render_visual_assets":
        if (r.status === "success") plan.assetCount = r.images_generated as number;
        break;
      case "assemble_campaign_payload": {
        if (r.status === "success") {
          const s = r.payload_summary as Record<string, unknown>;
          plan.campaignName = s.campaign_name as string;
          // micros 换算成元展示
          const micros = s.daily_budget_micros as number;
          if (micros != null) plan.dailyBudget = `¥${(micros / 1_000_000).toFixed(2)}`;
          plan.token = r.submission_token as string;
        }
        break;
      }
      case "submit_campaign_payload": {
        const receipt = r.receipt as Record<string, unknown> | undefined;
        if (receipt) {
          plan.submittedMode = receipt.mode as string;
          plan.committed = receipt.committed as boolean;
        }
        break;
      }
      case "monitor_new_campaign":
        if (r.severity) plan.monitorSeverity = r.severity as string;
        break;
    }
  }
  return plan;
}
