import { useEffect, useState } from "react";
import { RefreshCw, Save } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { CliParamField, CliParamsPayload } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  className?: string;
  reloadKey?: string | number;
  canManage?: boolean;
};

type DraftValues = Record<string, string | boolean>;

const CHAT_CONTROLLED_CLI_PARAM_KEYS = new Set(["model"]);
const MODEL_OPTION_NONE = "none";

function fieldLabel(key: string, field: CliParamField) {
  return field.description || key;
}

function buildDraftValues(payload: CliParamsPayload): DraftValues {
  const drafts: DraftValues = {};
  for (const [key, field] of Object.entries(payload.schema)) {
    const value = payload.params[key];
    if (field.type === "boolean") {
      drafts[key] = Boolean(value);
      continue;
    }
    if (field.type === "string_list") {
      drafts[key] = Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
      continue;
    }
    drafts[key] = value == null ? "" : String(value);
  }
  return drafts;
}

function visibleEntries(payload: CliParamsPayload) {
  return Object.entries(payload.schema).filter(([key]) => !CHAT_CONTROLLED_CLI_PARAM_KEYS.has(key));
}

function toRequestValue(field: CliParamField, value: string | boolean) {
  if (field.type === "boolean") {
    return Boolean(value);
  }
  if (field.type === "string_list") {
    return String(value)
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return value;
}

function toModelOptionValue(value: unknown, options: string[]) {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return options.includes(MODEL_OPTION_NONE) ? MODEL_OPTION_NONE : "";
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function BotCliParamsPanel({
  botAlias,
  client = new MockWebBotClient(),
  className = "",
  reloadKey = "",
  canManage = true,
}: Props) {
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [draftValues, setDraftValues] = useState<DraftValues>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setNotice("");
    void client.getCliParams(botAlias)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setCliParams(payload);
        setDraftValues(buildDraftValues(payload));
      })
      .catch((err) => {
        if (!cancelled) {
          setError(getErrorMessage(err, "加载 CLI 参数失败"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, client, reloadKey]);

  const entries = cliParams ? visibleEntries(cliParams) : [];
  const baseDrafts = cliParams ? buildDraftValues(cliParams) : {};
  const hasChanges = entries.some(([key]) => baseDrafts[key] !== (draftValues[key] ?? ""));

  async function save() {
    if (!cliParams || !canManage) {
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      let next = cliParams;
      for (const [key, field] of entries) {
        if (baseDrafts[key] === (draftValues[key] ?? "")) {
          continue;
        }
        next = await client.updateCliParam(botAlias, key, toRequestValue(field, draftValues[key] ?? ""));
      }
      setCliParams(next);
      setDraftValues(buildDraftValues(next));
      setNotice("参数已保存");
    } catch (err) {
      setError(getErrorMessage(err, "保存参数失败"));
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!canManage) {
      return;
    }
    setResetting(true);
    setError("");
    setNotice("");
    try {
      const currentModel = toModelOptionValue(cliParams?.params.model, cliParams?.schema.model?.enum ?? []);
      let next = await client.resetCliParams(botAlias);
      const nextModel = toModelOptionValue(next.params.model, next.schema.model?.enum ?? []);
      if (currentModel && nextModel !== currentModel) {
        next = await client.updateCliParam(botAlias, "model", currentModel, next.cliType);
      }
      setCliParams(next);
      setDraftValues(buildDraftValues(next));
      setNotice("CLI 参数已恢复默认值");
    } catch (err) {
      setError(getErrorMessage(err, "重置 CLI 参数失败"));
    } finally {
      setResetting(false);
    }
  }

  return (
    <section className={`rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 ${className}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">CLI 参数</h2>
          <p className="text-sm text-[var(--muted)]">当前 CLI: {cliParams?.cliType || "加载中"}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => void save()}
            disabled={!canManage || saving || !hasChanges}
            className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
          >
            <Save className="h-4 w-4" />
            {saving ? "保存中..." : "保存参数"}
          </button>
          <button
            type="button"
            onClick={() => void reset()}
            disabled={!canManage || resetting}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <RefreshCw className="h-4 w-4" />
            {resetting ? "重置中..." : "恢复默认参数"}
          </button>
        </div>
      </div>

      {error ? <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      {notice ? <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div> : null}
      {loading ? <div className="mt-4 text-sm text-[var(--muted)]">加载中...</div> : null}

      <div className="mt-4 space-y-3">
        {entries.map(([key, field]) => {
          const label = fieldLabel(key, field);
          const value = draftValues[key] ?? "";
          const inputId = `cli-param-${botAlias}-${key}`;

          if (field.type === "boolean") {
            return (
              <label
                key={key}
                htmlFor={inputId}
                className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm font-medium text-[var(--text)]"
              >
                <span>{label}</span>
                <input
                  id={inputId}
                  aria-label={label}
                  type="checkbox"
                  checked={Boolean(value)}
                  disabled={!canManage}
                  onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.checked }))}
                  className="h-4 w-4 shrink-0"
                />
              </label>
            );
          }

          return (
            <div key={key} className="space-y-2">
              <label htmlFor={inputId} className="block text-sm font-medium text-[var(--text)]">{label}</label>
              {field.enum ? (
                <select
                  id={inputId}
                  aria-label={label}
                  value={String(value)}
                  disabled={!canManage}
                  onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                >
                  {field.enum.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              ) : field.type === "string_list" ? (
                <textarea
                  id={inputId}
                  aria-label={label}
                  rows={3}
                  value={String(value)}
                  disabled={!canManage}
                  onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                  placeholder="每行一个参数"
                />
              ) : (
                <input
                  id={inputId}
                  aria-label={label}
                  type={field.type === "number" ? "number" : "text"}
                  value={String(value)}
                  disabled={!canManage}
                  onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                />
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
