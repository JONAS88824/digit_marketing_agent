"use client";

/** 人工确认卡——全界面的签名元素。
 *
 * 对应后端的 confirmation_request 事件（ADK 的 require_confirmation 拦截）。
 * 用户点按钮 → streamConfirm → 框架重新执行（或放弃）被拦的写操作。
 * 这是全系统唯一能改动广告账号的入口，所以视觉上要醒目、不可误触。
 */

const TOOL_LABELS: Record<string, string> = {
  submit_campaign_payload: "提交广告方案到 Google Ads",
  pause_campaign: "暂停广告系列",
};

export function ConfirmCard({
  toolName,
  args,
  hint,
  resolved,
  onConfirm,
  onCancel,
  busy,
}: {
  toolName: string;
  args: Record<string, unknown>;
  hint: string;
  resolved: "none" | "confirmed" | "cancelled";
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const label = TOOL_LABELS[toolName] ?? toolName;
  return (
    <div className="overflow-hidden rounded-lg border border-hairline border-l-4 border-l-[var(--warn)] bg-surface shadow-md">
      <div className="flex items-center gap-2 border-b border-[color-mix(in_srgb,var(--warn)_40%,transparent)] bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] px-3.5 py-2.5">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0">
          <path
            d="M8 1.8l5.6 2.4v4c0 3.2-2.3 5.4-5.6 6.2C4.7 13.6 2.4 11.4 2.4 8.2v-4L8 1.8z"
            stroke="var(--warn)"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <path d="M5.8 8l1.6 1.6 3-3" stroke="var(--warn)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="text-[13px] font-bold">需要你确认 · {label}</span>
      </div>
      <div className="flex flex-col gap-3 p-3.5">
        <div className="text-[13px] text-ink2">{hint || "这是一个写操作，执行前需要你亲自确认。"}</div>
        <details className="rounded-md border border-hairline bg-surface2 px-2.5 py-1.5">
          <summary className="cursor-pointer text-[12px] text-muted">查看操作参数</summary>
          <pre className="mt-2 max-h-48 overflow-auto font-mono text-[11px] leading-relaxed text-ink2">
            {JSON.stringify(args, null, 2)}
          </pre>
        </details>
        {resolved === "none" ? (
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              disabled={busy}
              onClick={onConfirm}
              className="rounded-md bg-accent px-4 py-2 text-[13.5px] font-semibold text-white hover:bg-accentstrong disabled:opacity-50"
            >
              {busy ? "执行中…" : "确认执行"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="rounded-md border border-hairline px-4 py-2 text-[13.5px] font-semibold text-ink2 hover:bg-surface2 hover:text-ink disabled:opacity-50"
            >
              取消
            </button>
            <span className="text-[12px] text-muted">演练模式下只生成回执，不动真实账户</span>
          </div>
        ) : (
          <div
            className={`text-[13px] font-semibold ${resolved === "confirmed" ? "text-goodtext" : "text-critical"}`}
          >
            {resolved === "confirmed" ? "✓ 已确认，正在执行…" : "✕ 已取消，本次不执行"}
          </div>
        )}
      </div>
    </div>
  );
}
