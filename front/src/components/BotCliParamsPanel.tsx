import { cliTypeLabel } from "../utils/cliType";
import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { LoaderCircle, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import {
  SettingsDirtyBadge,
  SettingsNotice,
  SettingsSection,
  SettingsSwitch,
  settingsControlClassName,
  settingsIconButtonClassName,
  settingsPrimaryButtonClassName,
  settingsTextareaClassName,
} from "./SettingsSection";
import type { CliParamField, CliParamsPayload } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  className?: string;
  reloadKey?: string | number;
  canManage?: boolean;
  /** "section" renders flat inside the settings page; "card" keeps a bordered card for other hosts. */
  variant?: "card" | "section";
};

type DraftValues = Record<string, string | boolean>;

const CHAT_CONTROLLED_CLI_PARAM_KEYS = ["provider", "model", "reasoning_effort", "effort"] as const;
const CHAT_CONTROLLED_CLI_PARAM_KEY_SET = new Set<string>(CHAT_CONTROLLED_CLI_PARAM_KEYS);
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
  return Object.entries(payload.schema).filter(([key]) => !CHAT_CONTROLLED_CLI_PARAM_KEY_SET.has(key));
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

function chatControlledParamValue(
  payload: CliParamsPayload,
  key: (typeof CHAT_CONTROLLED_CLI_PARAM_KEYS)[number],
) {
  if (!payload.schema[key]) {
    return "";
  }
  if (key === "model") {
    return toModelOptionValue(payload.params.model, payload.schema.model?.enum ?? []);
  }
  const value = payload.params[key];
  return typeof value === "string" ? value : "";
}

export function BotCliParamsPanel({
  botAlias,
  client = new MockWebBotClient(),
  className = "",
  reloadKey = "",
  canManage = true,
  variant = "card",
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
      const preservedValues = cliParams
        ? CHAT_CONTROLLED_CLI_PARAM_KEYS.map((key) => [key, chatControlledParamValue(cliParams, key)] as const)
        : [];
      let next = await client.resetCliParams(botAlias);
      for (const [key, currentValue] of preservedValues) {
        if (currentValue && chatControlledParamValue(next, key) !== currentValue) {
          next = await client.updateCliParam(botAlias, key, currentValue, next.cliType);
        }
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

  const booleanEntries = entries.filter(([, field]) => field.type === "boolean");
  const valueEntries = entries.filter(([, field]) => field.type !== "boolean");

  return (
    <SettingsSection
      id="settings-section-params"
      titleId={`bot-cli-params-title-${botAlias}`}
      icon={<SlidersHorizontal className="h-3.5 w-3.5" />}
      title="CLI 参数"
      description={`当前 CLI: ${cliParams ? cliTypeLabel(cliParams.cliType) : "加载中"}`}
      badge={hasChanges ? <SettingsDirtyBadge /> : null}
      className={variant === "card"
        ? clsx("@container rounded-lg border border-[var(--border)] bg-[var(--surface)] last:border-b", className)
        : className}
      actions={(
        <>
          <button
            type="button"
            aria-label="恢复默认参数"
            title="恢复默认参数"
            onClick={() => void reset()}
            disabled={!canManage || resetting}
            className={settingsIconButtonClassName}
          >
            <RotateCcw className={clsx("h-3.5 w-3.5", resetting ? "animate-spin" : "")} />
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={!canManage || saving || !hasChanges}
            className={settingsPrimaryButtonClassName}
          >
            {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {saving ? "保存中..." : "保存参数"}
          </button>
        </>
      )}
    >
      <div className="space-y-2.5">
        {error ? <SettingsNotice tone="danger">{error}</SettingsNotice> : null}
        {notice ? <SettingsNotice tone="success">{notice}</SettingsNotice> : null}
        {loading ? (
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            加载中...
          </div>
        ) : null}
        {cliParams?.cliType === "deepseek" ? (
          <div className="space-y-0.5 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2.5 py-1.5 text-[11px] leading-4 text-[var(--muted)]">
            <p>Provider、模型和思考深度可在聊天中原子选择；headless 模式下运行 pwsh 等工具需要选择 danger-full-access。</p>
            <p>
              当前 Provider：{cliParams.selectedProvider || String(cliParams.params.provider || "默认")}
              {cliParams.catalogStatus ? ` · catalog：${cliParams.catalogStatus}` : ""}
            </p>
            {cliParams.catalogDiagnostic ? <p className="text-[var(--status-warning)]">{cliParams.catalogDiagnostic}</p> : null}
          </div>
        ) : null}

        {valueEntries.length > 0 ? (
          <div className="grid gap-2 @md:grid-cols-2">
            {valueEntries.map(([key, field]) => {
              const label = fieldLabel(key, field);
              const value = draftValues[key] ?? "";
              const inputId = `cli-param-${botAlias}-${key}`;
              const changed = baseDrafts[key] !== value;
              return (
                <div key={key} className={clsx("min-w-0 space-y-1", field.type === "string_list" ? "@md:col-span-2" : "")}>
                  <label htmlFor={inputId} className="flex min-w-0 items-center gap-1 text-[11px] font-medium text-[var(--muted)]">
                    <span className="min-w-0 truncate" title={label}>{label}</span>
                    {changed ? <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--status-warning)]" /> : null}
                  </label>
                  {field.enum ? (
                    <select
                      id={inputId}
                      aria-label={label}
                      value={String(value)}
                      disabled={!canManage}
                      onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                      className={settingsControlClassName}
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
                      className={clsx(settingsTextareaClassName, "font-mono")}
                      placeholder="每行一个参数"
                      spellCheck={false}
                    />
                  ) : (
                    <input
                      id={inputId}
                      aria-label={label}
                      type={field.type === "number" ? "number" : "text"}
                      value={String(value)}
                      disabled={!canManage}
                      onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                      className={settingsControlClassName}
                    />
                  )}
                </div>
              );
            })}
          </div>
        ) : null}

        {booleanEntries.length > 0 ? (
          <div className="grid overflow-hidden rounded-md border border-[var(--workbench-hairline)] @md:grid-cols-2">
            {booleanEntries.map(([key, field]) => {
              const label = fieldLabel(key, field);
              const inputId = `cli-param-${botAlias}-${key}`;
              return (
                <label
                  key={key}
                  htmlFor={inputId}
                  className="-mb-px -mr-px flex min-h-9 min-w-0 cursor-pointer items-center justify-between gap-3 border-b border-r border-[var(--workbench-hairline)] px-2.5 py-1.5 text-xs transition-colors hover:bg-[var(--workbench-hover-bg)]"
                >
                  <span className="min-w-0 leading-4 text-[var(--text)]">{label}</span>
                  <SettingsSwitch
                    id={inputId}
                    aria-label={label}
                    checked={Boolean(draftValues[key])}
                    disabled={!canManage}
                    onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.checked }))}
                  />
                </label>
              );
            })}
          </div>
        ) : null}
      </div>
    </SettingsSection>
  );
}
