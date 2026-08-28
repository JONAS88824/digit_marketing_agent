"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { TopBar } from "@/components/TopBar";
import { Sidebar } from "@/components/Sidebar";
import { ChatThread } from "@/components/ChatThread";
import { Composer } from "@/components/Composer";
import { RightPanel } from "@/components/RightPanel";
import { ConfigModal } from "@/components/ConfigModal";
import {
  createSession,
  deleteSession,
  fetchConfigStatus,
  listSessions,
  streamChat,
  streamConfirm,
} from "@/lib/api";
import { derivePlan } from "@/lib/plan";
import type { ConfigStatus, Item, PendingAttachment, SessionInfo, SseEvent } from "@/lib/types";

export default function Page() {
  const [items, setItems] = useState<Item[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const idRef = useRef(0);
  const nextId = () => `i${++idRef.current}`;

  const refreshStatus = useCallback(() => {
    fetchConfigStatus().then(setStatus).catch(() => setStatus(null));
  }, []);
  const refreshSessions = useCallback(() => {
    listSessions().then(setSessions).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshStatus();
    refreshSessions();
  }, [refreshStatus, refreshSessions]);

  /* ============ SSE 事件 → 对话流条目 ============ */

  const handleEvent = useCallback((ev: SseEvent) => {
    if (ev.type === "done" || ev.type === "artifact") return;
    setItems((prev) => {
      const next = [...prev];
      switch (ev.type) {
        case "text": {
          const last = next[next.length - 1];
          // 同一位专员连续说话就合并成一段
          if (last && last.kind === "agent" && last.author === ev.author) {
            next[next.length - 1] = { ...last, text: last.text + ev.text };
          } else {
            next.push({ kind: "agent", id: nextId(), author: ev.author, text: ev.text });
          }
          break;
        }
        case "tool_call":
          if (ev.name === "transfer_to_agent") break; // transfer 事件会单独渲染
          next.push({ kind: "tool", id: ev.id, name: ev.name, args: ev.args });
          break;
        case "tool_result": {
          const idx = next.findIndex((i) => i.kind === "tool" && i.id === ev.id);
          if (idx !== -1) {
            next[idx] = { ...(next[idx] as Extract<Item, { kind: "tool" }>), result: ev.result };
          } else {
            next.push({ kind: "tool", id: ev.id, name: ev.name, args: {}, result: ev.result });
          }
          break;
        }
        case "transfer":
          next.push({ kind: "transfer", id: nextId(), to: ev.to });
          break;
        case "confirmation_request":
          next.push({
            kind: "confirmation",
            id: ev.id,
            toolName: ev.tool_name,
            args: ev.args,
            hint: ev.hint,
            resolved: "none",
          });
          break;
        case "error":
          next.push({ kind: "error", id: nextId(), message: ev.message });
          break;
      }
      return next;
    });
  }, []);

  /* ============ 发送与确认 ============ */

  const send = useCallback(
    async (text?: string, atts?: PendingAttachment[]) => {
      const message = (text ?? input).trim();
      const files = atts ?? attachments;
      if ((!message && files.length === 0) || busy) return;

      let sid = sessionId;
      if (!sid) {
        try {
          sid = await createSession();
          setSessionId(sid);
        } catch (e) {
          setItems((prev) => [...prev, { kind: "error", id: `e${Date.now()}`, message: `连不上后端：${String(e)}。先启动 server.py。` }]);
          return;
        }
      }

      setItems((prev) => [
        ...prev,
        { kind: "user", id: nextId(), text: message || "（看这些附件）", attachments: files.map((f) => f.filename) },
      ]);
      setInput("");
      setAttachments([]);
      setBusy(true);
      try {
        await streamChat({ sessionId: sid, message, attachments: files }, handleEvent);
        refreshSessions();
      } catch (e) {
        setItems((prev) => [...prev, { kind: "error", id: nextId(), message: `出错了：${String(e)}` }]);
      } finally {
        setBusy(false);
      }
    },
    [input, attachments, busy, sessionId, handleEvent, refreshSessions],
  );

  const answerConfirmation = useCallback(
    async (itemId: string, confirmed: boolean) => {
      if (!sessionId || busy) return;
      setItems((prev) =>
        prev.map((i) => (i.kind === "confirmation" && i.id === itemId ? { ...i, resolved: confirmed ? "confirmed" : "cancelled" } : i)),
      );
      setBusy(true);
      try {
        await streamConfirm({ sessionId, functionCallId: itemId, confirmed }, handleEvent);
      } catch (e) {
        setItems((prev) => [...prev, { kind: "error", id: nextId(), message: `确认流转出错：${String(e)}` }]);
      } finally {
        setBusy(false);
      }
    },
    [sessionId, busy, handleEvent],
  );

  /* ============ 会话管理 ============ */

  const newSession = useCallback(async () => {
    try {
      const sid = await createSession();
      setSessionId(sid);
      setItems([]);
      refreshSessions();
    } catch {
      /* 后端没起也不至于卡死界面 */
    }
  }, [refreshSessions]);

  const selectSession = useCallback(
    async (sid: string) => {
      setSessionId(sid);
      setItems([]);
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8001"}/api/sessions/${sid}/events`);
        if (res.ok) {
          const data = (await res.json()) as { events: SseEvent[] };
          for (const ev of data.events) {
            // 重放时确认卡一律标记为已处理（不能再点），避免误触发旧确认
            if (ev.type === "confirmation_request") {
              setItems((prev) => [
                ...prev,
                { kind: "confirmation", id: ev.id, toolName: ev.tool_name, args: ev.args, hint: ev.hint, resolved: "cancelled" },
              ]);
            } else {
              handleEvent(ev);
            }
          }
        }
      } catch {
        /* 历史加载失败不影响继续对话 */
      }
    },
    [handleEvent],
  );

  const removeSession = useCallback(
    async (sid: string) => {
      await deleteSession(sid).catch(() => undefined);
      if (sid === sessionId) {
        setSessionId(null);
        setItems([]);
      }
      refreshSessions();
    },
    [sessionId, refreshSessions],
  );

  const plan = derivePlan(items);

  return (
    <div className="flex h-dvh flex-col">
      <TopBar status={status} />
      {/* 网格行封顶 minmax(0,1fr)：防止某栏内容过高把整行撑出视口，
          顶掉中央栏底部的输入框（三栏都必须在栏内滚动） */}
      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] grid-cols-1 md:grid-cols-[236px_minmax(0,1fr)] xl:grid-cols-[236px_minmax(0,1fr)_300px]">
        <div className="hidden md:block">
          <Sidebar
            sessions={sessions}
            activeSessionId={sessionId}
            onNewSession={newSession}
            onSelectSession={selectSession}
            onPickQuestion={(q) => setInput(q)}
          />
        </div>
        <main className="flex min-w-0 flex-col">
          <ChatThread
            items={items}
            sessionId={sessionId ?? ""}
            busy={busy}
            onConfirm={(id) => answerConfirmation(id, true)}
            onCancel={(id) => answerConfirmation(id, false)}
          />
          <Composer
            value={input}
            onChange={setInput}
            onSend={() => send()}
            busy={busy}
            attachments={attachments}
            onAttachmentsChange={setAttachments}
          />
        </main>
        <div className="hidden xl:block">
          <RightPanel plan={plan} status={status} onOpenConfig={() => setConfigOpen(true)} />
        </div>
      </div>
      {configOpen ? (
        <ConfigModal
          onClose={() => setConfigOpen(false)}
          onSaved={() => {
            refreshStatus();
          }}
        />
      ) : null}
    </div>
  );
}
