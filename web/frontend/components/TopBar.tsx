"use client";

import type { ConfigStatus } from "@/lib/types";

/** 顶栏：三盏安全状态灯，对应 config.py 的三重安全阀。
 * 演示数据/演练模式 = 琥珀灯提醒，live = 绿灯。
 */
export function TopBar({ status }: { status: ConfigStatus | null }) {
  const lights = [
    {
      key: "数据源",
      value: status ? (status.data_source_mode === "live" ? "真实数据" : "演示数据") : "…",
      warn: status?.data_source_mode !== "live",
      title: "mock = 内置演示数据，不是真实投放数据；live = 真实 API（需凭证齐备）",
    },
    {
      key: "出图",
      value: status ? (status.image.effective_mode === "live" ? "真出图 · 按张计费" : "占位图") : "…",
      warn: status?.image.effective_mode === "live" ? false : false,
      title: "mock = 本地占位图零成本；live = 按张计费",
    },
    {
      key: "写入",
      value: status ? (status.ads_write.effective_mode === "live" ? "真实落盘" : "演练") : "…",
      warn: false,
      title: "演练模式只生成回执不动账户；真实落盘需显式打开 ADS_WRITE_MODE 且凭证齐备",
    },
  ];
  return (
    <header className="flex h-[52px] shrink-0 items-center gap-5 border-b border-hairline bg-surface px-4">
      <div className="flex items-baseline gap-2.5">
        <span className="text-base font-bold">投放作战室</span>
        <span className="font-mono text-[11px] text-muted">digital_marketing_agent</span>
      </div>
      <div className="flex-1" />
      <div className="flex gap-2">
        {lights.map((l) => (
          <span
            key={l.key}
            title={l.title}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs text-ink2 ${
              l.warn
                ? "border-[color-mix(in_srgb,var(--warn)_55%,transparent)] bg-[color-mix(in_srgb,var(--warn)_14%,transparent)]"
                : "border-hairline bg-surface2"
            }`}
          >
            <span
              className={`h-[7px] w-[7px] rounded-full ${
                l.warn ? "bg-[var(--warn)]" : l.value.includes("live") || l.value.includes("真实") || l.value.includes("真出图") ? "bg-good" : "bg-baseline"
              }`}
            />
            <span className="hidden text-muted sm:inline">{l.key}</span>
            {l.value}
          </span>
        ))}
      </div>
    </header>
  );
}
