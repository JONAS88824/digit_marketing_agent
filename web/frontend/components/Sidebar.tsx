"use client";

import type { SessionInfo } from "@/lib/types";

const SPECIALISTS = [
  {
    name: "投放表现分析",
    question: "最近一周投放怎么样",
    path: "M2 13l3.5-5 3 3L14 3",
    risk: false,
  },
  {
    name: "关键词规划",
    question: "运动户外该投什么词",
    path: "M8.8 8.8L14 14M9.6 6.4a3.6 3.6 0 11-5.2 5A3.6 3.6 0 019.6 6.4z",
    risk: false,
  },
  {
    name: "文案与视觉创意",
    question: "给跑鞋写套广告文案",
    path: "M3 13.2c2-1 2.4-2.8 2-4.4M7.2 13.2c3.6-1.8 5.6-5.2 5.4-9.4C8.8 3.8 5.2 5.6 3.6 9c-.7 1.6-.2 3.2 1.2 3.6 1.6.5 3.6-.3 5-1.8",
    risk: false,
  },
  {
    name: "投放策略与风控",
    question: "这套方案能上线吗",
    path: "M8 1.8l5.6 2.4v4c0 3.2-2.3 5.4-5.6 6.2C4.7 13.6 2.4 11.4 2.4 8.2v-4L8 1.8z",
    risk: true,
  },
];

export function Sidebar({
  sessions,
  activeSessionId,
  onNewSession,
  onSelectSession,
  onPickQuestion,
}: {
  sessions: SessionInfo[];
  activeSessionId: string | null;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onPickQuestion: (question: string) => void;
}) {
  return (
    <aside className="flex h-full flex-col gap-4 overflow-y-auto border-r border-hairline bg-surface p-3">
      <button
        type="button"
        onClick={onNewSession}
        className="flex items-center justify-center gap-1.5 rounded-md border border-accent bg-[color-mix(in_srgb,var(--accent)_8%,transparent)] px-2.5 py-2 text-[13px] font-semibold text-accentstrong hover:bg-accent hover:text-white"
      >
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
          <path d="M6.5 1v11M1 6.5h11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        新建对话
      </button>

      <div>
        <div className="px-1.5 pb-1.5 font-mono text-[10.5px] uppercase tracking-widest text-muted">会话</div>
        <div className="flex flex-col gap-0.5">
          {sessions.length === 0 ? (
            <div className="px-2.5 py-1.5 text-xs text-muted">还没有会话</div>
          ) : (
            sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                onClick={() => onSelectSession(s.session_id)}
                className={`flex items-center justify-between gap-1.5 rounded-md px-2.5 py-2 text-left text-[13px] ${
                  s.session_id === activeSessionId ? "bg-surface3 font-semibold text-ink" : "text-ink2 hover:bg-surface2"
                }`}
              >
                <span className="truncate">{s.title || "新对话"}</span>
                <span className="shrink-0 font-mono text-[10.5px] text-muted">
                  {s.updated_at ? new Date(s.updated_at * 1000).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }) : ""}
                </span>
              </button>
            ))
          )}
        </div>
        <div className="px-2.5 pt-1 text-[10.5px] text-muted">
          当前为内存会话，重启后端后历史消失（学习阶段够用）。
        </div>
      </div>

      <div>
        <div className="px-1.5 pb-1.5 font-mono text-[10.5px] uppercase tracking-widest text-muted">专员</div>
        <div className="flex flex-col gap-0.5">
          {SPECIALISTS.map((sp) => (
            <button
              key={sp.name}
              type="button"
              onClick={() => onPickQuestion(sp.question)}
              className="grid grid-cols-[18px_1fr] items-start gap-2 rounded-md px-2.5 py-2 text-left hover:bg-surface2"
              title={`点击把「${sp.question}」填进输入框，可以修改后再发送`}
            >
              <svg width="15" height="15" viewBox="0 0 16 16" fill="none" className="mt-0.5">
                <path
                  d={sp.path}
                  stroke={sp.risk ? "var(--serious)" : "var(--accent)"}
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="flex flex-col">
                <span className="text-[13px] font-semibold">{sp.name}</span>
                <span className="text-xs text-muted">「{sp.question}」</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
