"use client";

import { useRef, useState } from "react";

type Point = { day: string; value: number | null };

/** 逐日趋势折线图：内联 SVG 实现，无图表库依赖。
 *
 * 悬停显示当天的数值（十字线 + 提示框）。
 * value 为 null 的天（0 除数等）跳过连线。
 */
export function TrendChart({
  points,
  unit,
}: {
  points: Point[];
  unit?: string;
}) {
  const W = 660;
  const H = 232;
  const PL = 52;
  const PR = 16;
  const PT = 18;
  const PB = 32;
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const valid = points.map((p, i) => ({ ...p, i })).filter((p) => p.value != null) as (Point & { i: number; value: number })[];
  if (valid.length < 2) {
    return <div className="py-8 text-center text-[13px] text-muted">数据点太少，画不出趋势</div>;
  }

  const values = valid.map((p) => p.value);
  let yMin = Math.min(...values);
  let yMax = Math.max(...values);
  if (yMax === yMin) {
    yMin -= 1;
    yMax += 1;
  }
  const pad = (yMax - yMin) * 0.08;
  yMin -= pad;
  yMax += pad;

  const xOf = (i: number) => PL + (i / (points.length - 1)) * (W - PL - PR);
  const yOf = (v: number) => PT + ((yMax - v) / (yMax - yMin)) * (H - PT - PB);

  // 三条网格线取整值
  const steps = 3;
  const gridVals = Array.from({ length: steps }, (_, k) => yMin + ((yMax - yMin) * (k + 0.5)) / steps);

  const linePath = valid
    .map((p, k) => `${k === 0 ? "M" : "L"}${xOf(p.i).toFixed(1)},${yOf(p.value).toFixed(1)}`)
    .join("");
  const areaPath = `${linePath}L${xOf(valid[valid.length - 1].i).toFixed(1)},${H - PB}L${xOf(valid[0].i).toFixed(1)},${H - PB}Z`;

  const last = valid[valid.length - 1];
  const hoverPoint = hover != null ? valid.find((p) => p.i === hover) : null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="block h-auto w-full"
        role="img"
        aria-label={`逐日趋势图，${points.length} 天`}
        onMouseMove={(e) => {
          const rect = svgRef.current?.getBoundingClientRect();
          if (!rect) return;
          const mx = ((e.clientX - rect.left) / rect.width) * W;
          let best = 0;
          let bestD = Infinity;
          for (const p of valid) {
            const d = Math.abs(xOf(p.i) - mx);
            if (d < bestD) {
              bestD = d;
              best = p.i;
            }
          }
          setHover(best);
        }}
        onMouseLeave={() => setHover(null)}
      >
        {gridVals.map((v, k) => (
          <g key={k}>
            <line x1={PL} x2={W - PR} y1={yOf(v)} y2={yOf(v)} stroke="var(--hairline)" strokeWidth="1" />
            <text x={PL - 8} y={yOf(v) + 3.5} textAnchor="end" fontSize="10" fill="var(--muted)" fontFamily="var(--font-mono)">
              {v.toFixed(v >= 100 ? 0 : 1)}
            </text>
          </g>
        ))}
        <line x1={PL} x2={W - PR} y1={H - PB} y2={H - PB} stroke="var(--baseline)" strokeWidth="1" />
        {points.map((p, i) =>
          i % 2 === 0 ? (
            <text key={i} x={xOf(i)} y={H - PB + 16} textAnchor="middle" fontSize="10" fill="var(--muted)" fontFamily="var(--font-mono)">
              {p.day.slice(5)}
            </text>
          ) : null,
        )}
        <path d={areaPath} fill="var(--accent)" opacity="0.1" />
        <path d={linePath} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {valid.map((p) => (
          <circle key={p.i} cx={xOf(p.i)} cy={yOf(p.value)} r="2.4" fill="var(--surface)" stroke="var(--accent)" strokeWidth="1.5" />
        ))}
        {/* 终点直接标注 */}
        <circle cx={xOf(last.i)} cy={yOf(last.value)} r="3.6" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
        <text x={xOf(last.i) - 4} y={yOf(last.value) - 10} textAnchor="end" fontSize="11" fontWeight="600" fill="var(--ink)" fontFamily="var(--font-mono)">
          {last.value.toFixed(2)}
        </text>
        {/* 悬停十字线 */}
        {hoverPoint ? (
          <g pointerEvents="none">
            <line x1={xOf(hoverPoint.i)} x2={xOf(hoverPoint.i)} y1={PT} y2={H - PB} stroke="var(--baseline)" strokeWidth="1" strokeDasharray="3 3" />
            <circle cx={xOf(hoverPoint.i)} cy={yOf(hoverPoint.value)} r="4" fill="none" stroke="var(--accent)" strokeWidth="2" />
          </g>
        ) : null}
      </svg>
      {hoverPoint ? (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-md bg-ink px-2 py-1 font-mono text-[11px] text-page"
          style={{
            left: `${(xOf(hoverPoint.i) / W) * 100}%`,
            top: `${(yOf(hoverPoint.value) / H) * 100}%`,
            transform: "translate(-50%, -130%)",
          }}
        >
          {hoverPoint.day.slice(5)} · {hoverPoint.value.toFixed(2)}
          {unit === "百分比" ? "%" : ""}
        </div>
      ) : null}
    </div>
  );
}
