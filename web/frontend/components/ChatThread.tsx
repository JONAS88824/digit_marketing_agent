"use client";

import { useEffect, useRef } from "react";
import type { Item } from "@/lib/types";
import { agentLabel } from "@/lib/meta";
import { ToolCard } from "./cards";
import { ConfirmCard } from "./ConfirmCard";

/** 轨迹条上的参数摘要：挑前两个短的标量参数（如 metric=cpc · 14 天）。
 *
 * 同一个工具会被连续调用多次（比如先查 CPC 再查 CTR 的逐日趋势），
 * 只显示工具名的话两条轨迹一模一样，看不出哪条对哪张卡——
 * 带上参数才能把"调用 → 结果"的配对关系摆在明面上。
 */
function argsSummary(args: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args ?? {})) {
    if (v == null || v === "" || parts.length >= 2) continue;
    if (Array.isArray(v)) {
      if (v.length > 0 && v.length <= 2 && v.every((x) => typeof x === "string" || typeof x === "number")) {
        parts.push(`${k}=${v.join(",")}`);
      }
      continue;
    }
    if (typeof v === "object") continue;
    const s = String(v);
    if (s.length > 18) continue; // 太长的值不进摘要（完整参数在确认卡/折叠面板里看）
    parts.push(`${k}=${s}`);
  }
  return parts.join(" · ");
}

export function ChatThread({
  items,
  sessionId,
  busy,
  onConfirm,
  onCancel,
}: {
  items: Item[];
  sessionId: string;
  busy: boolean;
  onConfirm: (id: string) => void;
  onCancel: (id: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [items]);

  return (
    <div
      ref={scrollRef}
      className="min-h-0 flex-1 overflow-y-auto bg-surface px-6 py-5"
      onScroll={(e) => {
        const el = e.currentTarget;
        stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      }}
    >
      <div className="mx-auto flex max-w-[760px] flex-col gap-5">
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="text-lg font-bold">投放作战室</div>
            <div className="max-w-[46ch] text-[13.5px] text-ink2">
              问点什么开始——比如「最近一周投放怎么样」「运动户外该投什么词」，
              或者从左栏的四位专员里挑一个。写操作一律需要你确认后才执行。
            </div>
          </div>
        ) : null}

        {items.map((item) => {
          switch (item.kind) {
            case "user":
              return (
                <div key={item.id} className="flex flex-col items-end gap-1">
                  {item.attachments && item.attachments.length > 0 ? (
                    <div className="flex gap-1.5">
                      {item.attachments.map((a, i) => (
                        <span key={i} className="rounded border border-hairline bg-surface2 px-2 py-0.5 font-mono text-[10.5px] text-muted">
                          {a}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <div className="max-w-[78%] rounded-xl rounded-br-sm bg-accent px-3.5 py-2.5 text-[13.5px] text-white">
                    {item.text}
                  </div>
                </div>
              );

            case "transfer":
              return (
                <div key={item.id} className="flex items-center gap-2.5 py-0.5 text-[12.5px] text-muted">
                  <span className="h-px flex-1 bg-hairline" />
                  <span className="whitespace-nowrap font-semibold text-ink2">→ 已转交 · {agentLabel(item.to)}</span>
                  <span className="h-px flex-1 bg-hairline" />
                </div>
              );

            case "agent":
              return (
                <div key={item.id} className="flex flex-col gap-1.5">
                  <div className="text-xs">
                    <span className="font-bold">{agentLabel(item.author)}</span>
                    <span className="ml-2 font-mono text-muted">{item.author}</span>
                  </div>
                  <div className="max-w-[68ch] whitespace-pre-wrap text-[14px] leading-relaxed">{item.text}</div>
                </div>
              );

            case "tool": {
              if (item.name === "transfer_to_agent") return null; // transfer 事件已渲染成分隔线
              return (
                <div key={item.id} className="flex flex-col gap-1.5">
                  <div className="inline-flex items-center gap-2 self-start rounded-md border border-hairline bg-surface2 px-2.5 py-1 font-mono text-[11px] text-muted">
                    {item.result == null ? (
                      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
                    ) : (
                      <span>▸</span>
                    )}
                    <span className="text-ink2">{item.name}</span>
                    {argsSummary(item.args) ? (
                      <span className="text-muted">{argsSummary(item.args)}</span>
                    ) : null}
                    {item.result == null ? <span className="text-ink2">调用中…</span> : null}
                  </div>
                  {item.result != null ? <ToolCard name={item.name} result={item.result} sessionId={sessionId} /> : null}
                </div>
              );
            }

            case "confirmation":
              return (
                <ConfirmCard
                  key={item.id}
                  toolName={item.toolName}
                  args={item.args}
                  hint={item.hint}
                  resolved={item.resolved}
                  busy={busy}
                  onConfirm={() => onConfirm(item.id)}
                  onCancel={() => onCancel(item.id)}
                />
              );

            case "error":
              return (
                <div
                  key={item.id}
                  className="rounded-lg border border-[color-mix(in_srgb,var(--critical)_40%,transparent)] bg-[color-mix(in_srgb,var(--critical)_8%,transparent)] px-3.5 py-2.5 text-[13px] text-critical"
                >
                  {item.message}
                </div>
              );
          }
        })}

        {busy && items[items.length - 1]?.kind !== "tool" ? (
          <div className="flex items-center gap-2 text-[13px] text-muted">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
            思考中…
          </div>
        ) : null}
      </div>
    </div>
  );
}
