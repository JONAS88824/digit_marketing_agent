"use client";

import { useCallback, useEffect, useState } from "react";
import type { ConfigGroup, ConfigSchema, TestResult } from "@/lib/types";
import { fetchConfigSchema, saveConfig, testConnectivity } from "@/lib/api";

/** 配置中心：schema 驱动渲染（分组和键名来自后端 /api/config/schema，
 * 后端又从 config.py 生成——加数据源只改 config.py，前端零改动）。
 *
 * 安全规则延续设计稿：凭证只写不读，已配置项只显示徽章不回显值。
 */
export function ConfigModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [schema, setSchema] = useState<ConfigSchema | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [provider, setProvider] = useState("google");
  const [tests, setTests] = useState<Record<string, TestResult | "testing">>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetchConfigSchema()
      .then((s) => {
        setSchema(s);
        const initial: Record<string, string> = {};
        for (const g of s.groups) {
          for (const f of g.fields) {
            if (f.type === "select" && f.value) initial[f.key] = f.value;
          }
        }
        setValues(initial);
      })
      .catch((e) => setMessage(`加载配置清单失败：${String(e)}`));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = useCallback((key: string, value: string) => {
    setValues((v) => ({ ...v, [key]: value }));
  }, []);

  /** 换 provider：模型列表与 API key 字段名随之刷新（与设计稿一致的联动） */
  const changeProvider = useCallback(
    (p: string) => {
      setProvider(p);
      if (!schema) return;
      const models = schema.provider_models[p] ?? [];
      set("MODEL_PROVIDER", p);
      set("MODEL", models[0] ?? "");
      const keyName = schema.provider_keys[p] ?? "API_KEY";
      setApiKeyLabel(keyName);
    },
    [schema, set],
  );

  // API key 行的键名跟随 provider 变化（google/anthropic/openai 各自的 key）
  const [apiKeyLabel, setApiKeyLabel] = useState("GOOGLE_API_KEY");

  const runTest = async (source: string) => {
    setTests((t) => ({ ...t, [source]: "testing" }));
    try {
      const r = await testConnectivity(source);
      setTests((t) => ({ ...t, [source]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [source]: { source, result: "fail", detail: String(e) } }));
    }
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const msg = await saveConfig(values);
      setMessage(msg);
      onSaved();
      setTimeout(onClose, 1200);
    } catch (e) {
      setMessage(`保存失败：${String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const renderTestStatus = (g: ConfigGroup) => {
    if (!g.source) return null;
    const t = tests[g.source];
    if (t === "testing") return <span className="text-[11.5px] text-muted">检测中…</span>;
    if (!t) return <span className="text-[11.5px] text-muted">未检测</span>;
    if (t.result === "ok") return <span className="text-[11.5px] font-semibold text-goodtext">✓ 连通正常</span>;
    if (t.result === "pending") return <span className="text-[11.5px] font-semibold text-muted">{t.detail}</span>;
    return <span className="text-[11.5px] font-semibold text-critical">未通过 · {t.detail}</span>;
  };

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/45 p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="配置中心"
        className="flex max-h-full w-[min(640px,100%)] flex-col overflow-hidden rounded-xl border border-hairline bg-surface shadow-2xl"
      >
        <div className="flex items-center gap-2.5 border-b border-hairline px-4.5 py-3.5">
          <span className="text-[15px] font-bold">配置中心</span>
          <span className="text-xs text-muted">快速填写 .env → 检测连通性 → 保存后生效</span>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4.5 pb-3.5 pt-1.5">
          {schema == null ? (
            <div className="py-10 text-center text-[13px] text-muted">加载配置清单…</div>
          ) : (
            schema.groups.map((g) => (
              <div key={g.name} className="border-b border-hairline py-3 last:border-b-0">
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-[13px] font-bold">{g.name}</span>
                  <span className="flex-1" />
                  {g.source ? (
                    <button
                      type="button"
                      onClick={() => runTest(g.source!)}
                      className="rounded-md border border-hairline bg-surface2 px-2.5 py-0.5 text-[11.5px] font-semibold text-ink2 hover:border-accent hover:text-accentstrong"
                    >
                      测连通
                    </button>
                  ) : null}
                  {renderTestStatus(g)}
                </div>
                {g.fields.map((f) => {
                  const isApiKeyRow = g.name.startsWith("模型与引擎") && f.secret;
                  const label = isApiKeyRow ? apiKeyLabel : f.key;
                  return (
                    <div key={`${g.name}-${f.key}`} className="grid grid-cols-[200px_1fr_auto] items-center gap-2 py-1">
                      <span className="break-all font-mono text-[11px] text-ink2">
                        {label}
                        {f.note ? <span className="block font-sans text-[10.5px] text-muted">{f.note}</span> : null}
                      </span>
                      {f.type === "select" ? (
                        <select
                          className="w-full rounded-md border border-hairline bg-surface px-2 py-1.5 font-mono text-xs text-ink focus:border-accent focus:outline-none"
                          value={values[f.key] ?? f.value ?? ""}
                          onChange={(e) => {
                            if (f.key === "MODEL_PROVIDER") changeProvider(e.target.value);
                            else set(f.key, e.target.value);
                          }}
                        >
                          {(f.options ?? []).map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={f.type === "password" ? "password" : "text"}
                          className="w-full rounded-md border border-hairline bg-surface px-2 py-1.5 font-mono text-xs text-ink focus:border-accent focus:outline-none"
                          placeholder={f.configured ? "已配置 · 填新值可覆盖" : ""}
                          onChange={(e) => set(f.key, e.target.value)}
                        />
                      )}
                      {f.configured ? (
                        <span className="whitespace-nowrap rounded bg-[color-mix(in_srgb,var(--good)_12%,transparent)] px-1.5 py-px text-[10.5px] font-semibold text-goodtext">
                          已配置
                        </span>
                      ) : (
                        <span />
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className="flex items-center gap-2.5 border-t border-hairline bg-surface2 px-4.5 py-3">
          <span className="flex-1 text-[11.5px] text-muted">
            {message || "保存 = 写入 .env 并重载配置，即时生效。凭证值只在填写时出现，保存后不再回显。"}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-hairline px-4 py-2 text-[13.5px] font-semibold text-ink2 hover:bg-surface hover:text-ink"
          >
            取消
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={save}
            className="rounded-md bg-accent px-4 py-2 text-[13.5px] font-semibold text-white hover:bg-accentstrong disabled:opacity-50"
          >
            {saving ? "保存中…" : "保存并生效"}
          </button>
        </div>
      </div>
    </div>
  );
}
