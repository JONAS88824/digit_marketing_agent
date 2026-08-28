/** 后端 SSE 事件的形状（与 web/server.py 的 _translate_event 一一对应） */

export type SseEvent =
  | { type: "text"; text: string; author: string }
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown>; author: string }
  | { type: "tool_result"; id: string; name: string; result: unknown; author: string }
  | {
      type: "confirmation_request";
      id: string;
      tool_name: string;
      args: Record<string, unknown>;
      hint: string;
      author: string;
    }
  | { type: "transfer"; to: string; from: string }
  | { type: "artifact"; filenames: string[]; session_id: string }
  | { type: "done" }
  | { type: "error"; message: string };

/** 对话流里的一个展示单元 */
export type Item =
  | { kind: "user"; id: string; text: string; attachments?: string[] }
  | { kind: "transfer"; id: string; to: string }
  | { kind: "agent"; id: string; author: string; text: string }
  | { kind: "tool"; id: string; name: string; args: Record<string, unknown>; result?: unknown }
  | {
      kind: "confirmation";
      id: string;
      toolName: string;
      args: Record<string, unknown>;
      hint: string;
      resolved: "none" | "confirmed" | "cancelled";
    }
  | { kind: "error"; id: string; message: string };

/** 待上传的附件（Composer 收集，随消息一起发） */
export type PendingAttachment = {
  filename: string;
  mime_type: string;
  data: string; // base64，不带 data:xxx;base64, 前缀
};

export type SessionInfo = { session_id: string; title?: string; updated_at: number | null };

export type SourceStatusInfo = {
  credentials_configured: boolean;
  missing_keys: string[];
  library_installed: boolean;
  missing_package: string | null;
  fetch_implemented: boolean;
  ready_for_live: boolean;
  effective_mode: string;
  remaining_work: string[];
};

export type ConfigStatus = {
  data_source_mode: string;
  image: { effective_mode: string; api_key_configured: boolean; max_images_per_call: number };
  ads_write: { effective_mode: string; credentials_configured: boolean; write_implemented: boolean };
  sources: Record<string, SourceStatusInfo>;
  note: string;
};

export type ConfigField = {
  key: string;
  type: "text" | "password" | "select";
  note?: string;
  value?: string;
  options?: { value: string; label: string }[];
  configured?: boolean;
  secret?: boolean;
  optional?: boolean;
};

export type ConfigGroup = {
  name: string;
  source?: string;
  fields: ConfigField[];
};

export type ConfigSchema = {
  groups: ConfigGroup[];
  provider_models: Record<string, string[]>;
  provider_keys: Record<string, string>;
};

export type TestResult = { source: string; result: string; detail: string };

/** 右栏"当前方案"的聚合状态：从工具返回值里提取 */
export type PlanState = {
  keywordCandidates?: number;
  keywordClusters?: number;
  keywordTotal?: number;
  negativeCount?: number;
  copyReady?: boolean;
  assetCount?: number;
  campaignName?: string;
  dailyBudget?: string;
  token?: string;
  submittedMode?: string;
  committed?: boolean;
  monitorSeverity?: string;
};
