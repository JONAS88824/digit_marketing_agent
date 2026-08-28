import type {
  ConfigSchema,
  ConfigStatus,
  PendingAttachment,
  SessionInfo,
  SseEvent,
  TestResult,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8001";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* 非 JSON 错误体就用状态码 */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/* ============ 会话 ============ */

export async function createSession(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/sessions`, { method: "POST" });
  const data = await json<{ session_id: string }>(res);
  return data.session_id;
}

export async function listSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${API_BASE}/api/sessions`);
  const data = await json<{ sessions: SessionInfo[] }>(res);
  return data.sessions;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/api/sessions/${sessionId}`, { method: "DELETE" });
}

/* ============ 配置体检与配置中心 ============ */

export async function fetchConfigStatus(): Promise<ConfigStatus> {
  return json(await fetch(`${API_BASE}/api/config/status`));
}

export async function fetchConfigSchema(): Promise<ConfigSchema> {
  return json(await fetch(`${API_BASE}/api/config/schema`));
}

export async function saveConfig(values: Record<string, string>): Promise<string> {
  const res = await fetch(`${API_BASE}/api/config/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  const data = await json<{ message: string }>(res);
  return data.message;
}

export async function testConnectivity(source: string): Promise<TestResult> {
  const res = await fetch(`${API_BASE}/api/config/test/${source}`, { method: "POST" });
  return json(res);
}

/* ============ 对话（SSE 流） ============ */

/** 读一个 SSE 响应体，把每条 data: 事件喂给 onEvent。
 *
 * fetch 没有内建的 POST SSE，这里手动读流、按空行分包。
 */
async function consumeSse(res: Response, onEvent: (ev: SseEvent) => void): Promise<void> {
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    // SSE 事件之间以空行分隔
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as SseEvent);
          } catch {
            /* 单行解析失败不该断流 */
          }
        }
      }
    }
  }
}

export async function streamChat(
  params: {
    sessionId: string;
    message: string;
    attachments?: PendingAttachment[];
  },
  onEvent: (ev: SseEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: params.sessionId,
      message: params.message,
      attachments: params.attachments ?? [],
    }),
  });
  await consumeSse(res, onEvent);
}

export async function streamConfirm(
  params: { sessionId: string; functionCallId: string; confirmed: boolean },
  onEvent: (ev: SseEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: params.sessionId,
      function_call_id: params.functionCallId,
      confirmed: params.confirmed,
    }),
  });
  await consumeSse(res, onEvent);
}

/* ============ 产物 ============ */

/** render_visual_assets 生成到 generated/ 的图 */
export function generatedImageUrl(filename: string): string {
  return `${API_BASE}/api/generated/${encodeURIComponent(filename)}`;
}

/** inspect_visual_asset 存进 artifact 服务的图 */
export function artifactImageUrl(sessionId: string, filename: string): string {
  return `${API_BASE}/api/artifacts/${sessionId}/${encodeURIComponent(filename)}`;
}
