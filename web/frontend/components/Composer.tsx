"use client";

import { useRef, useState } from "react";
import type { PendingAttachment } from "@/lib/types";

/** 把用户选的文件读成 base64 附件 */
function readAttachment(file: File): Promise<PendingAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result);
      const base64 = dataUrl.split(",")[1] ?? "";
      resolve({ filename: file.name, mime_type: file.type || "application/octet-stream", data: base64 });
    };
    reader.onerror = () => reject(new Error(`读取 ${file.name} 失败`));
    reader.readAsDataURL(file);
  });
}

export function Composer({
  value,
  onChange,
  onSend,
  busy,
  attachments,
  onAttachmentsChange,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  busy: boolean;
  attachments: PendingAttachment[];
  onAttachmentsChange: (list: PendingAttachment[]) => void;
}) {
  const [skillsOpen, setSkillsOpen] = useState(false);
  const imageInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const pickFiles = async (files: FileList | null, images: boolean) => {
    if (!files) return;
    const next: PendingAttachment[] = [];
    for (const f of Array.from(files)) {
      if (f.size > 4 * 1024 * 1024) {
        alert(`${f.name} 超过 4MB，跳过`);
        continue;
      }
      if (images && !f.type.startsWith("image/")) {
        alert(`${f.name} 不是图片，请用"上传文件"`);
        continue;
      }
      next.push(await readAttachment(f));
    }
    onAttachmentsChange([...attachments, ...next]);
  };

  return (
    <div className="shrink-0 border-t border-hairline bg-surface px-6 pb-3.5 pt-3">
      <div className="mx-auto max-w-[760px]">
        {attachments.length > 0 ? (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {attachments.map((a, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-surface2 px-2 py-1 font-mono text-[11px] text-ink2"
              >
                {a.mime_type.startsWith("image/") ? "🖼" : "📄"}
                {a.filename}
                <button
                  type="button"
                  className="text-muted hover:text-critical"
                  onClick={() => onAttachmentsChange(attachments.filter((_, j) => j !== i))}
                  aria-label={`移除 ${a.filename}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        ) : null}

        <div className="flex items-center gap-1.5 rounded-[10px] border border-hairline bg-surface px-2 py-1 shadow-sm focus-within:border-accent">
          <input
            ref={fileInput}
            type="file"
            multiple
            className="hidden"
            accept=".txt,.md,.csv,.json,text/*"
            onChange={(e) => {
              pickFiles(e.target.files, false);
              e.target.value = "";
            }}
          />
          <input
            ref={imageInput}
            type="file"
            multiple
            className="hidden"
            accept="image/*"
            onChange={(e) => {
              pickFiles(e.target.files, true);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            className="flex h-[30px] w-[30px] items-center justify-center rounded-md text-muted hover:bg-surface2 hover:text-ink"
            title="上传文件（词表 / 文案稿 / 预算表，文本类）"
            aria-label="上传文件"
            onClick={() => fileInput.current?.click()}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M13.2 7.6l-6 6a3.4 3.4 0 01-4.8-4.8l6.9-6.9a2.3 2.3 0 013.2 3.2l-6.6 6.6a1.1 1.1 0 01-1.6-1.6l5.9-5.9" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <button
            type="button"
            className="flex h-[30px] w-[30px] items-center justify-center rounded-md text-muted hover:bg-surface2 hover:text-ink"
            title="上传图片（可直接发给创意专员做素材诊断）"
            aria-label="上传图片"
            onClick={() => imageInput.current?.click()}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="2" y="3" width="12" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
              <circle cx="5.8" cy="6.3" r="1.1" fill="currentColor" />
              <path d="M2.6 11.6l3.3-3 2.6 2.3 2.4-2.5 2.5 2.7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <div className="relative">
            <button
              type="button"
              className="flex h-[30px] w-[30px] items-center justify-center rounded-md text-muted hover:bg-surface2 hover:text-ink"
              title="加载技能（SkillToolset）"
              aria-label="加载技能"
              aria-expanded={skillsOpen}
              onClick={() => setSkillsOpen(!skillsOpen)}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8.8 1.5L3.2 9h3.9l-.9 5.5L11.9 7H8l.8-5.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
              </svg>
            </button>
            {skillsOpen ? (
              <div className="absolute bottom-10 left-0 z-10 w-64 rounded-lg border border-hairline bg-surface p-2.5 shadow-xl">
                <div className="mb-1.5 text-xs font-bold">技能 Skills</div>
                <div className="mb-1.5 text-[11.5px] text-muted">当前 agent 未挂载技能包。将来可挂载：</div>
                <div className="flex flex-col gap-0.5 text-[12.5px] text-ink2">
                  <div className="rounded-md px-2 py-1.5 hover:bg-surface2"><b className="text-ink">品牌规范</b> — 文案语气与用词红线</div>
                  <div className="rounded-md px-2 py-1.5 hover:bg-surface2"><b className="text-ink">投放 SOP</b> — 行业出价与预算套路</div>
                  <div className="rounded-md px-2 py-1.5 hover:bg-surface2"><b className="text-ink">平台政策速查</b> — 素材审核清单</div>
                </div>
                <div className="mt-1.5 border-t border-dashed border-hairline pt-1.5 text-[10.5px] text-muted">
                  接入方式：SkillToolset(skills=[...])，见 demo_skill_agent 的用法。
                </div>
              </div>
            ) : null}
          </div>

          <input
            className="min-w-0 flex-1 bg-transparent py-2 text-[14px] text-ink outline-none placeholder:text-muted"
            placeholder="问点什么，比如「最近一周投放怎么样」"
            value={value}
            aria-label="输入问题"
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing && !busy) onSend();
            }}
          />
          <button
            type="button"
            className="rounded-md bg-accent px-4 py-1.5 text-[13px] font-semibold text-white hover:bg-accentstrong disabled:opacity-50"
            disabled={busy || (!value.trim() && attachments.length === 0)}
            onClick={onSend}
          >
            发送
          </button>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-3.5 px-0.5 text-[11.5px] text-muted">
          <span>图片可直接用于素材诊断</span>
          <span>写操作一律需要你确认</span>
          <span>会话内支持省略句</span>
        </div>
      </div>
    </div>
  );
}
