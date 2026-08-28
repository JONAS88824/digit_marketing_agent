"use client";

import { Card, CheckRow, Chip, MiniTable, NoteBox, Stat, WarnBox } from "../ui";

type Dict = Record<string, unknown>;

type Check = {
  check: string;
  label: string;
  passed: boolean;
  severity?: string | null;
  actual?: unknown;
  limit?: unknown;
  message?: string;
};

function checksCard(
  result: Dict,
  title: string,
  pick: () => { all: Check[]; blocking: Check[]; warnings: Check[] },
) {
  const { all, blocking, warnings } = pick();
  return (
    <div className="flex flex-col gap-2.5">
      <Card title={title} tone={blocking.length > 0 ? "critical" : warnings.length > 0 ? "warn" : undefined}>
        <div className="flex flex-col">
          {all.map((c, i) => (
            <CheckRow
              key={i}
              ok={c.passed}
              warn={!c.passed && c.severity === "warning"}
              title={`${c.label}${c.passed ? " · 通过" : ""}`}
              detail={
                c.passed
                  ? c.limit != null && c.actual != null
                    ? `实际 ${String(c.actual)} / 上限 ${String(c.limit)}`
                    : c.message
                  : c.message ?? ""
              }
            />
          ))}
        </div>
      </Card>
      {blocking.length > 0 ? (
        <WarnBox>
          <b>有 {blocking.length} 项未过阀门：</b>
          {blocking.map((b) => b.label).join("、")}。越界的项必须改方案，不能跳过。
        </WarnBox>
      ) : null}
      {result.next_step ? <NoteBox>{String(result.next_step)}</NoteBox> : null}
    </div>
  );
}

/** review_budget_and_bidding：预算与出价阀门 */
export function BudgetReviewCard({ result }: { result: Dict }) {
  return checksCard(result, `预算与出价阀门 · ${result.campaign_name ?? ""}`, () => {
    const all = (result.all_checks ?? []) as Check[];
    return {
      all,
      blocking: (result.blocking ?? []) as Check[],
      warnings: (result.warnings ?? []) as Check[],
    };
  });
}

/** screen_policy_compliance：合规审查 */
export function ComplianceCard({ result }: { result: Dict }) {
  const sensitive = (result.sensitive_words ?? {}) as Dict;
  const blockingHits = (sensitive.blocking_hits ?? []) as Dict[];
  const warningHits = (sensitive.warning_hits ?? []) as Dict[];
  const adCopy = (result.ad_copy ?? {}) as Dict;
  const keywordHits = (result.keyword_rule_hits ?? []) as Dict[];
  return (
    <div className="flex flex-col gap-2.5">
      <Card
        title="合规审查"
        tone={blockingHits.length > 0 ? "critical" : warningHits.length > 0 ? "warn" : undefined}
        hint="敏感词五类扫描 · 抗规避归一化"
      >
        <div className="flex flex-col">
          {blockingHits.map((h, i) => (
            <CheckRow
              key={`b${i}`}
              ok={false}
              title={`敏感词命中 · ${h.category}`}
              detail={`${h.section}「${h.text}」含「${h.word}」——${h.reason}`}
            />
          ))}
          {warningHits.map((h, i) => (
            <CheckRow
              key={`w${i}`}
              ok={false}
              warn
              title={`提示 · ${h.category}`}
              detail={`${h.section}「${h.text}」含「${h.word}」——${h.reason}`}
            />
          ))}
          {((adCopy.over_limit_texts ?? []) as Dict[]).map((t, i) => (
            <CheckRow
              key={`o${i}`}
              ok={false}
              title={`${t.kind}超字符限制`}
              detail={`「${t.text}」超出 ${t.over_by_units} 单位`}
            />
          ))}
          {keywordHits.map((h, i) => (
            <CheckRow
              key={`k${i}`}
              ok={false}
              warn
              title={`关键词规则命中 · ${h.keyword}`}
              detail={`${(h.matched_words as string[])?.join("、")}——${h.reason}`}
            />
          ))}
          {blockingHits.length === 0 && warningHits.length === 0 && keywordHits.length === 0 ? (
            <CheckRow ok title="敏感词与规则扫描全部通过" detail="五类敏感词、字符规则、负向词规则均无命中" />
          ) : null}
        </div>
      </Card>
      {result.your_turn ? <NoteBox>{String(result.your_turn)}</NoteBox> : null}
    </div>
  );
}

/** assemble_campaign_payload：Mutate 方案构造回执 */
export function AssembleCard({ result }: { result: Dict }) {
  if (result.status === "blocked") {
    const blocking = (result.blocking ?? []) as string[];
    return (
      <div className="flex flex-col gap-2.5">
        <Card title="方案构造被拦截" tone="critical" hint="先解决下面的问题才能拿到提交 token">
          <div className="flex flex-col gap-1.5 text-[13px]">
            {blocking.map((b, i) => (
              <div key={i} className="text-critical">· {b}</div>
            ))}
          </div>
        </Card>
      </div>
    );
  }
  const s = (result.payload_summary ?? {}) as Dict;
  const byResource = (s.operations_by_resource ?? {}) as Record<string, number>;
  const order = (s.execution_order ?? []) as Dict[];
  return (
    <div className="flex flex-col gap-2.5">
      <Card title="Mutate 方案已构造" hint={`原子提交 · 新系列以 ${String(s.initial_campaign_status)} 状态创建 · ${result.write_mode === "live" ? "真实落盘" : "演练模式"}`}>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Stat label="广告系列" value={String(s.campaign_name ?? "—")} />
            <Stat label="操作总数" value={String(s.operation_count)} />
            <Stat label="日预算" value={`¥${(Number(s.daily_budget_micros) / 1_000_000).toFixed(2)}`} note="micros 已换算" />
            <Stat label="匹配类型" value={String(s.keyword_match_type)} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(byResource).map(([res, n]) => (
              <Chip key={res} variant="default">
                {res} × {n}
              </Chip>
            ))}
          </div>
          <MiniTable
            columns={[
              { key: "step", header: "顺序", align: "right", render: (r) => String(r.step) },
              { key: "res", header: "资源", render: (r) => String(r.resource) },
              { key: "dep", header: "依赖", render: (r) => (r.waits_for as number[])?.join("、") || "—" },
            ]}
            rows={order}
            maxHeight={180}
          />
          <div className="flex items-center gap-2 rounded-md border border-hairline bg-surface2 px-2.5 py-1.5 font-mono text-[12px] text-ink2">
            幂等 token
            <span className="font-semibold">{String(result.submission_token)}</span>
            <span className="text-[11px] text-muted">方案被改动后失效 · 重复提交只返回上次回执</span>
          </div>
        </div>
      </Card>
      {((result.warnings ?? []) as string[]).length > 0 ? (
        <WarnBox>{((result.warnings ?? []) as string[]).join("；")}</WarnBox>
      ) : null}
      {result.next_step ? <NoteBox>{String(result.next_step)}</NoteBox> : null}
    </div>
  );
}

/** submit_campaign_payload / pause_campaign：提交回执 */
export function ReceiptCard({ result, action }: { result: Dict; action: string }) {
  const receipt = (result.receipt ?? result.result ?? {}) as Dict;
  return (
    <div className="flex flex-col gap-2.5">
      <Card
        title={action}
        tone={receipt.committed ? "critical" : "warn"}
        hint={receipt.committed ? "已真实落盘" : "演练模式 · 只生成回执，不动真实账户"}
      >
        <div className="flex flex-col gap-2.5">
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <Stat label="对象" value={String(receipt.campaign ?? "—")} />
            {receipt.operation_count != null ? <Stat label="操作数" value={String(receipt.operation_count)} /> : null}
            <Stat label="模式" value={String(receipt.mode ?? "—")} />
          </div>
          {receipt.created_resources ? (
            <div className="flex flex-wrap gap-1.5">
              {(receipt.created_resources as string[]).map((r, i) => (
                <Chip key={i} variant="default">{r}</Chip>
              ))}
            </div>
          ) : null}
          {receipt.note ? <div className="text-[12.5px] text-muted">{String(receipt.note)}</div> : null}
          {receipt.idempotent_replay ? <NoteBox>幂等命中：这个 token 之前提交过，本次直接返回上次的回执，没有重复创建。</NoteBox> : null}
        </div>
      </Card>
      {result.report_requirement ? <NoteBox>{String(result.report_requirement)}</NoteBox> : null}
    </div>
  );
}

/** monitor_new_campaign：冷启动护航 */
export function MonitorCard({ result }: { result: Dict }) {
  if (result.status === "no_data") {
    return (
      <Card title="冷启动监控" hint="没有找到该系列的投放数据">
        <div className="text-[13px] text-muted">{String(result.message ?? "")}</div>
      </Card>
    );
  }
  const tripped = (result.tripped_rules ?? []) as Dict[];
  const perDay = (result.per_day ?? []) as Dict[];
  const severity = String(result.severity);
  return (
    <div className="flex flex-col gap-2.5">
      <Card
        title={`冷启动护航 · ${String(result.campaign)}`}
        tone={severity === "critical" ? "critical" : severity === "warning" ? "warn" : undefined}
        hint={`${String(result.window_days)} 天窗口 · 日预算 ¥${Number(result.daily_budget).toFixed(2)}`}
      >
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip variant={severity === "ok" ? "pass" : severity === "warning" ? "warn" : "fail"}>
              {severity === "ok" ? "运行正常" : severity === "warning" ? "有预警" : "触发熔断"}
            </Chip>
            {tripped.map((r, i) => (
              <Chip key={i} variant={r.severity === "critical" ? "fail" : "warn"}>
                {String(r.rule)}：{String(r.detail)}
              </Chip>
            ))}
          </div>
          <MiniTable
            columns={[
              { key: "day", header: "日期", render: (r) => String(r.day).slice(5) },
              { key: "cost", header: "花费", align: "right", render: (r) => `¥${Number(r.cost).toFixed(2)}` },
              { key: "ratio", header: "消耗/预算", align: "right", render: (r) => (r.spend_ratio != null ? `${(Number(r.spend_ratio) * 100).toFixed(0)}%` : "—") },
              { key: "clicks", header: "点击", align: "right", render: (r) => String(r.clicks) },
              { key: "ctr", header: "CTR", align: "right", render: (r) => (r.ctr_pct != null ? `${Number(r.ctr_pct).toFixed(2)}%` : "—") },
              { key: "cpc", header: "CPC", align: "right", render: (r) => (r.cpc != null ? `¥${Number(r.cpc).toFixed(2)}` : "—") },
              { key: "conv", header: "转化", align: "right", render: (r) => String(r.conversions) },
            ]}
            rows={perDay}
            maxHeight={240}
          />
        </div>
      </Card>
      <NoteBox>
        {String(result.recommended_action ?? "")}
        {result.no_auto_action ? "（熔断只产出待批的暂停动作，由你确认后执行——系统不会自动改账户。）" : ""}
      </NoteBox>
    </div>
  );
}
