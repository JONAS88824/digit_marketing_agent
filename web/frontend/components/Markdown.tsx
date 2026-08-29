"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** 专员的回复按 Markdown 渲染（粗体/列表/表格/代码）。
 *
 * 样式逐元素手工定制（不走 typography 插件），保证用设计令牌配色。
 * 专员指令要求"能用表格说清的数据就用表格"，所以开了 GFM 表格。
 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="max-w-[68ch] text-[14px] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-2.5 last:mb-0">{children}</p>,
          h1: ({ children }) => <h1 className="mb-2 mt-1 text-lg font-bold">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 mt-1 text-base font-bold">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1.5 mt-1 text-[15px] font-bold">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-1.5 mt-1 text-[14px] font-bold">{children}</h4>,
          ul: ({ children }) => <ul className="mb-2.5 ml-5 list-disc space-y-1 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-2.5 ml-5 list-decimal space-y-1 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          blockquote: ({ children }) => (
            <blockquote className="mb-2.5 border-l-[3px] border-accent bg-[color-mix(in_srgb,var(--accent)_8%,transparent)] px-3 py-1.5 text-ink2 last:mb-0">
              {children}
            </blockquote>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-accentstrong underline underline-offset-2">
              {children}
            </a>
          ),
          hr: () => <hr className="my-3 border-hairline" />,
          code: ({ className, children }) => {
            const isBlock = String(className || "").startsWith("language-");
            if (isBlock) {
              return (
                <code className="block overflow-x-auto rounded-md bg-surface2 p-2.5 font-mono text-[12px] leading-relaxed text-ink2">
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded bg-surface2 px-1.5 py-0.5 font-mono text-[12.5px] text-ink2">{children}</code>
            );
          },
          pre: ({ children }) => <pre className="mb-2.5 last:mb-0">{children}</pre>,
          table: ({ children }) => (
            <div className="mb-2.5 overflow-x-auto last:mb-0">
              <table className="w-full border-collapse text-[13px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead>{children}</thead>,
          th: ({ children }) => (
            <th className="whitespace-nowrap border-b border-hairline px-2.5 py-1.5 text-left text-[11.5px] font-semibold tracking-wide text-muted">
              {children}
            </th>
          ),
          td: ({ children }) => <td className="whitespace-nowrap border-b border-hairline px-2.5 py-1.5 tnum last:border-b-0">{children}</td>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
