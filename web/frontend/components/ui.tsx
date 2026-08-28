"use client";

import { ReactNode } from "react";

/* ============ 卡片壳 ============ */

export function Card({
  title,
  hint,
  children,
  tone,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  tone?: "default" | "warn" | "critical";
}) {
  const border =
    tone === "warn"
      ? "border-l-4 border-l-[var(--warn)]"
      : tone === "critical"
        ? "border-l-4 border-l-[var(--critical)]"
        : "";
  return (
    <div
      className={`overflow-hidden rounded-lg border border-hairline bg-surface shadow-sm ${border}`}
    >
      <div
        className={`flex items-center gap-2 border-b border-hairline px-3.5 py-2.5 ${
          tone === "warn" ? "bg-[color-mix(in_srgb,var(--warn)_14%,transparent)]" : ""
        }`}
      >
        <span className="text-[13px] font-bold">{title}</span>
        {hint ? <span className="text-xs text-muted">{hint}</span> : null}
      </div>
      <div className="p-3.5">{children}</div>
    </div>
  );
}

/* ============ 徽章 ============ */

export function Chip({
  children,
  variant = "default",
  title,
}: {
  children: ReactNode;
  variant?: "default" | "up" | "accent" | "pass" | "warn" | "fail";
  title?: string;
}) {
  const styles: Record<string, string> = {
    default: "border-hairline bg-surface2 text-ink2",
    up: "border-transparent bg-[color-mix(in_srgb,var(--good)_12%,transparent)] text-goodtext",
    accent:
      "border-transparent bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] text-accentstrong",
    pass: "border-transparent bg-[color-mix(in_srgb,var(--good)_12%,transparent)] text-goodtext",
    warn: "border-[color-mix(in_srgb,var(--warn)_45%,transparent)] bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] text-ink2",
    fail: "border-transparent bg-[color-mix(in_srgb,var(--critical)_10%,transparent)] text-critical",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-px text-[11px] font-semibold ${styles[variant]}`}
    >
      {children}
    </span>
  );
}

/** 环比涨跌徽章：颜色跟 verdict（后端已按指标语义判好方向） */
export function DeltaChip({
  changePct,
  verdict,
}: {
  changePct: number | null;
  verdict: string;
}) {
  if (changePct == null || verdict === "unknown") {
    return <Chip variant="default">—</Chip>;
  }
  const arrow = changePct >= 0 ? "↑" : "↓";
  const pct = `${arrow} ${Math.abs(changePct).toFixed(0)}%`;
  const label =
    verdict === "improved" ? "变好" : verdict === "worsened" ? "变差" : "正常波动";
  const variant = verdict === "improved" ? "up" : verdict === "worsened" ? "fail" : "default";
  return (
    <Chip variant={variant}>
      {pct} · {label}
    </Chip>
  );
}

/* ============ 提示条 ============ */

export function WarnBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-[color-mix(in_srgb,var(--warn)_45%,transparent)] bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] px-3 py-2 text-[13px] text-ink2">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="mt-0.5 shrink-0">
        <path d="M7 1.6L13 12H1L7 1.6z" stroke="var(--warn)" strokeWidth="1.4" strokeLinejoin="round" />
        <path d="M7 5.6v2.6M7 10.4v.5" stroke="var(--warn)" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
      <span>{children}</span>
    </div>
  );
}

export function NoteBox({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-r-md border-l-[3px] border-accent bg-[color-mix(in_srgb,var(--accent)_8%,transparent)] px-3 py-2 text-[13px] text-ink2">
      {children}
    </div>
  );
}

/* ============ 检查行（审查清单用） ============ */

export function CheckRow({
  ok,
  warn,
  title,
  detail,
}: {
  ok: boolean;
  warn?: boolean;
  title: string;
  detail?: string;
}) {
  const color = ok ? "var(--good-text)" : warn ? "var(--warn)" : "var(--critical)";
  return (
    <div
      className={`grid grid-cols-[20px_1fr] gap-2.5 px-3.5 py-2 text-[13px] ${
        !ok && !warn
          ? "bg-[color-mix(in_srgb,var(--critical)_8%,transparent)]"
          : !ok && warn
            ? "bg-[color-mix(in_srgb,var(--warn)_12%,transparent)]"
            : ""
      } border-b border-hairline last:border-b-0`}
    >
      <span className="flex justify-center pt-px">
        {ok ? (
          <svg width="15" height="15" viewBox="0 0 14 14" fill="none">
            <path d="M2 7.2l3 3L12 3.4" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg width="15" height="15" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="6" stroke={color} strokeWidth="1.4" />
            <path d="M7 4v3.6M7 9.8v.6" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        )}
      </span>
      <span>
        <span className="font-semibold" style={{ color: ok ? undefined : color }}>
          {title}
        </span>
        {detail ? <div className="mt-px text-[12.5px] text-ink2">{detail}</div> : null}
      </span>
    </div>
  );
}

/* ============ 通用表格 ============ */

export type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right";
  render: (row: T) => ReactNode;
};

export function MiniTable<T>({
  columns,
  rows,
  maxHeight,
}: {
  columns: Column<T>[];
  rows: T[];
  maxHeight?: number;
}) {
  return (
    <div className="overflow-x-auto" style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}>
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`whitespace-nowrap border-b border-hairline px-3 py-1.5 text-[11.5px] font-semibold tracking-wide text-muted ${
                  c.align === "right" ? "text-right" : "text-left"
                }`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`whitespace-nowrap border-b border-hairline px-3 py-2 last:border-b-0 ${
                    c.align === "right" ? "text-right tnum" : ""
                  }`}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ============ 指标小卡 ============ */

export function Stat({
  label,
  value,
  children,
  note,
}: {
  label: string;
  value: string;
  children?: ReactNode;
  note?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-hairline bg-surface px-3 py-2.5">
      <span className="text-[11.5px] tracking-wide text-muted">{label}</span>
      <span className="text-2xl font-bold leading-tight tnum">{value}</span>
      {children ? <div className="mt-0.5">{children}</div> : null}
      {note ? <span className="mt-px text-[10.5px] text-muted">{note}</span> : null}
    </div>
  );
}
