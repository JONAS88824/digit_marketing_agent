"use client";

import { Card, Chip, MiniTable, NoteBox, WarnBox } from "../ui";
import { generatedImageUrl, artifactImageUrl } from "@/lib/api";

type Dict = Record<string, unknown>;

/** get_product_usps：卖点六维度原料 */
export function UspCard({ result }: { result: Dict }) {
  const byAngle = (result.usps_by_angle ?? {}) as Record<string, { fact: string; proof: string }[]>;
  const missing = (result.missing_angles ?? []) as string[];
  return (
    <Card title={`「${String(result.product)}」卖点原料`} hint="六维度铺开，缺料维度会标出">
      <div className="flex flex-col gap-2.5">
        {Object.entries(byAngle).map(([angle, usps]) => (
          <div key={angle}>
            <span className="mb-1 block text-[11.5px] font-semibold tracking-wide text-muted">{angle}</span>
            <div className="flex flex-col gap-1">
              {usps.map((u, i) => (
                <div key={i} className="text-[13px]">
                  · {u.fact}
                  {u.proof ? <span className="text-muted">（{u.proof}）</span> : null}
                </div>
              ))}
            </div>
          </div>
        ))}
        {missing.length > 0 ? (
          <WarnBox>这些维度缺料：{missing.join("、")}。缺的角度写不出有说服力的文案，建议补原料。</WarnBox>
        ) : null}
      </div>
    </Card>
  );
}

type CopyDetail = {
  text: string;
  width_units: number;
  limit_units: number;
  remaining_cjk_chars: number;
  within_limit: boolean;
  issues: string[];
};

function CopyRow({ detail }: { detail: CopyDetail }) {
  const pct = Math.min(100, (detail.width_units / detail.limit_units) * 100);
  const over = !detail.within_limit;
  return (
    <div className="flex flex-col gap-1">
      <div className="grid grid-cols-[1fr_auto] items-baseline gap-2.5">
        <span className="text-[14px] font-semibold">{detail.text}</span>
        <span className={`font-mono text-[11px] ${over ? "text-critical" : "text-muted"}`}>
          {detail.width_units} / {detail.limit_units}
          {over ? " · 超限" : ""}
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-surface3">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: over ? "var(--critical)" : "var(--accent)" }}
        />
      </div>
      {over ? (
        <span className="text-[11.5px] text-critical">
          超出 {detail.width_units - detail.limit_units} 单位 ≈ 需删 {Math.ceil((detail.width_units - detail.limit_units) / 2)} 个汉字
        </span>
      ) : detail.issues?.length ? (
        <span className="text-[11.5px] text-muted">{detail.issues.join("；")}</span>
      ) : null}
    </div>
  );
}

/** validate_ad_copy：RSA 字符校验 */
export function AdCopyCard({ result }: { result: Dict }) {
  const headlines = (result.headline_details ?? []) as CopyDetail[];
  const descriptions = (result.description_details ?? []) as CopyDetail[];
  const summary = (result.summary ?? {}) as Dict;
  const mustFix = (result.must_fix ?? []) as string[];
  const warnings = (result.warnings ?? []) as string[];
  return (
    <div className="flex flex-col gap-2.5">
      <Card
        title="RSA 文案校验"
        hint={`全角字符按 Google 口径算 2 单位 · ${String(summary.headline_count)} 标题 / ${String(summary.description_count)} 描述`}
      >
        <div className="flex flex-col gap-3">
          <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">标题（上限 30 单位）</span>
          <div className="flex flex-col gap-2.5">
            {headlines.map((h, i) => (
              <CopyRow key={i} detail={h} />
            ))}
          </div>
          <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">描述（上限 90 单位）</span>
          <div className="flex flex-col gap-2.5">
            {descriptions.map((d, i) => (
              <CopyRow key={i} detail={d} />
            ))}
          </div>
        </div>
      </Card>
      {mustFix.length > 0 ? <WarnBox><b>必须修：</b>{mustFix.join("；")}</WarnBox> : null}
      {warnings.length > 0 ? <NoteBox>{warnings.join("；")}</NoteBox> : null}
      <div className="text-[12.5px] text-muted">
        {result.ready_to_submit ? (
          <Chip variant="pass">全部通过 · 可提交</Chip>
        ) : (
          <Chip variant="warn">需修改后才能提交</Chip>
        )}
      </div>
    </div>
  );
}

/** render_visual_assets：出图画廊 */
export function VisualAssetsCard({ result }: { result: Dict }) {
  const assets = (result.assets ?? []) as Dict[];
  const okAssets = assets.filter((a) => !a.error);
  const failed = assets.filter((a) => a.error);
  return (
    <div className="flex flex-col gap-2.5">
      <Card
        title={`视觉素材 · ${String(result.images_generated)} 张`}
        hint={`${String(result.quality_tier)} 档 · ${String(result.model_display_name)} · ${result.mode === "live" ? "真出图" : "占位图模式"}`}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {okAssets.map((a, i) => {
            const file = String(a.file ?? "");
            const filename = file.split(/[\\/]/).pop() ?? "";
            const ratio = String(a.ratio ?? "");
            return (
              <div key={i} className="relative overflow-hidden rounded-lg border border-hairline bg-surface2">
                {a.is_placeholder ? (
                  <span className="absolute left-1.5 top-1.5 z-10 rounded border border-[color-mix(in_srgb,var(--warn)_50%,transparent)] bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] px-1.5 py-px text-[10px] font-semibold text-ink2">
                    占位图 · 不能投放
                  </span>
                ) : null}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={generatedImageUrl(filename)}
                  alt={`${a.label} 素材`}
                  className="w-full"
                  style={{ aspectRatio: ratio.replace(":", " / "), objectFit: "cover" }}
                />
                <div className="flex justify-between border-t border-hairline px-2 py-1.5 font-mono text-[10.5px] text-muted">
                  <span>{String(a.label)}</span>
                  <span>{String(a.pixels)}</span>
                </div>
              </div>
            );
          })}
        </div>
        {failed.length > 0 ? (
          <div className="mt-2 text-[12px] text-critical">
            失败 {failed.length} 张：{failed.map((a) => `${a.label}（${a.error}）`).join("；")}
          </div>
        ) : null}
      </Card>
      {result.cost_note ? <NoteBox>{String(result.cost_note)}</NoteBox> : null}
    </div>
  );
}

/** inspect_visual_asset：素材客观诊断 */
export function InspectAssetCard({ result, sessionId }: { result: Dict; sessionId: string }) {
  const metrics = (result.objective_metrics ?? {}) as Dict;
  const size = result.size_compliance as Dict | null;
  const legibility = result.text_legibility as Dict | null;
  const artifactName = result.artifact_name as string | null;
  const dominant = (metrics.dominant_colors ?? []) as Dict[];
  return (
    <div className="flex flex-col gap-2.5">
      <Card title="素材诊断 · 客观指标" hint="Pillow 实测，不含主观判断">
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap gap-1.5">
            <Chip variant="default">{String(metrics.width)} × {String(metrics.height)} · {String(metrics.aspect_ratio)}</Chip>
            <Chip variant="default">{String(metrics.file_size_kb)} KB</Chip>
            <Chip variant={metrics.contrast_verdict === "对比度良好" ? "pass" : "warn"}>对比度：{String(metrics.contrast_verdict)}</Chip>
            {size ? <Chip variant={size.compliant ? "pass" : "warn"}>尺寸偏差 {Number(size.deviation_pct).toFixed(1)}%</Chip> : null}
            {legibility ? (
              <Chip variant={legibility.passes ? "pass" : "fail"}>
                叠字对比度 {String(legibility.recommended_text_color)} · {legibility.passes ? "达 WCAG 4.5" : "不达标"}
              </Chip>
            ) : null}
          </div>
          {dominant.length > 0 ? (
            <div className="flex items-center gap-2">
              <span className="text-[11.5px] text-muted">主色</span>
              {dominant.slice(0, 4).map((c, i) => (
                <span key={i} className="flex items-center gap-1 font-mono text-[10.5px] text-muted">
                  <span
                    className="inline-block h-3.5 w-3.5 rounded border border-hairline"
                    style={{ background: String(c.hex) }}
                  />
                  {Number(c.share_pct).toFixed(0)}%
                </span>
              ))}
            </div>
          ) : null}
          <MiniTable
            columns={[
              { key: "cell", header: "九宫格区域", render: (r) => String(r.cell) },
              { key: "share", header: "视觉能量占比", align: "right", render: (r) => `${(Number(r.share) * 100).toFixed(1)}%` },
            ]}
            rows={(metrics.grid_energy ?? []) as Dict[]}
            maxHeight={200}
          />
          {artifactName && sessionId ? (
            <div className="overflow-hidden rounded-lg border border-hairline">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={artifactImageUrl(sessionId, artifactName)} alt="被诊断的素材" className="max-h-72 w-full object-contain" />
            </div>
          ) : null}
        </div>
      </Card>
      {result.your_turn ? <NoteBox>{String(result.your_turn)}</NoteBox> : null}
    </div>
  );
}
