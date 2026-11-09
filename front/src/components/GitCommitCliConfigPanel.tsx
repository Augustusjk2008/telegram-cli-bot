import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import { LoaderCircle, RotateCcw, Save, Sparkles } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  CliParamField,
  CliType,
  GitCommitMessageCliConfig,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  gitIconButtonClassName,
  gitInputClassName,
  gitPrimaryButtonClassName,
  gitSegmentClass,
  gitSegmentGroupClassName,
} from "../screens/gitStyles";
import { defaultCliPathForType } from "../screens/useBotManager";
import { getErrorMessage } from "../utils/errorMessage";

const METHOD_OPTIONS: Array<{ value: "cli" | "llm"; label: string }> = [
  { value: "cli", label: "本地 CLI" },
  { value: "llm", label: "LLM API" },
];

const fieldLabelClassName = "block truncate text-[11px] text-[var(--muted)]";

const textareaClassName = clsx(
  "block min-h-[3.25rem] w-full resize-y rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2 py-1 font-mono text-xs leading-5 text-[var(--text)] outline-none transition-colors",
  "placeholder:font-sans placeholder:text-[var(--muted)] focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60",
);

type Props = {
  botAlias: string;
  client?: WebBotClient;
  canManage?: boolean;
  disabledReason?: string;
  className?: string;
};

type DraftValues = Record<string, string | boolean>;

function buildDraftValues(payload: GitCommitMessageCliConfig): DraftValues {
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
    if (value == null && field.enum?.includes("none")) {
      drafts[key] = "none";
      continue;
    }
    if (value == null && field.enum?.includes("default")) {
      drafts[key] = "default";
      continue;
    }
    drafts[key] = value == null ? "" : String(value);
  }
  return drafts;
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
  if (field.type === "number") {
    const trimmed = String(value).trim();
    if (!trimmed) {
      return null;
    }
    return Number(trimmed);
  }
  return String(value);
}

export function GitCommitCliConfigPanel({
  botAlias,
  client = new MockWebBotClient(),
  canManage = true,
  disabledReason = "",
  className = "",
}: Props) {
  const [config, setConfig] = useState<GitCommitMessageCliConfig | null>(null);
  const [draftValues, setDraftValues] = useState<DraftValues>({});
  const [methodDraft, setMethodDraft] = useState<"cli" | "llm">("cli");
  const [cliTypeDraft, setCliTypeDraft] = useState<CliType>("codex");
  const [cliPathDraft, setCliPathDraft] = useState("");
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
    if (disabledReason) {
      setConfig(null);
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }
    void client.getGitCommitMessageConfig(botAlias)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setConfig(payload);
        setMethodDraft(payload.method || "cli");
        setCliTypeDraft(payload.cliType);
        setCliPathDraft(payload.cliPath);
        setDraftValues(buildDraftValues(payload));
      })
      .catch((err) => {
        if (!cancelled) {
          setError(getErrorMessage(err, "加载 Commit Message CLI 配置失败"));
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
  }, [botAlias, client, disabledReason]);

  const entries = useMemo(() => Object.entries(config?.schema || {}), [config]);
  const baseDrafts = useMemo(() => (config ? buildDraftValues(config) : {}), [config]);
  const hasChanges = useMemo(() => {
    if (!config) {
      return false;
    }
    if (cliTypeDraft !== config.cliType || cliPathDraft !== config.cliPath) {
      return true;
    }
    if (methodDraft !== (config.method || "cli")) {
      return true;
    }
    return entries.some(([key]) => baseDrafts[key] !== (draftValues[key] ?? ""));
  }, [baseDrafts, cliPathDraft, cliTypeDraft, config, draftValues, entries, methodDraft]);

  async function save() {
    if (!config || !canManage) {
      return;
    }
    if (methodDraft === "cli" && cliTypeDraft === "deepseek") {
      setError("DeepSeek Harness 暂不支持生成提交信息，请选择其他 CLI");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const nextParams: Record<string, unknown> = {};
      for (const [key, field] of entries) {
        const draft = draftValues[key] ?? "";
        if (baseDrafts[key] === draft) {
          continue;
        }
        nextParams[key] = toRequestValue(field, draft);
      }
      const next = await client.updateGitCommitMessageConfig(botAlias, {
        method: methodDraft,
        cliType: cliTypeDraft,
        cliPath: cliPathDraft.trim(),
        ...(Object.keys(nextParams).length > 0 ? { params: nextParams } : {}),
      });
      setConfig(next);
      setMethodDraft(next.method || "cli");
      setCliTypeDraft(next.cliType);
      setCliPathDraft(next.cliPath);
      setDraftValues(buildDraftValues(next));
      setNotice("Commit Message CLI 配置已保存");
    } catch (err) {
      setError(getErrorMessage(err, "保存 Commit Message CLI 配置失败"));
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
      const next = await client.resetGitCommitMessageConfig(botAlias);
      setConfig(next);
      setMethodDraft(next.method || "cli");
      setCliTypeDraft(next.cliType);
      setCliPathDraft(next.cliPath);
      setDraftValues(buildDraftValues(next));
      setNotice("Commit Message CLI 已恢复默认值");
    } catch (err) {
      setError(getErrorMessage(err, "重置 Commit Message CLI 失败"));
    } finally {
      setResetting(false);
    }
  }

  const fieldEntries = entries.filter(([, field]) => field.type !== "boolean" && field.type !== "string_list");
  const booleanEntries = entries.filter(([, field]) => field.type === "boolean");
  const listEntries = entries.filter(([, field]) => field.type === "string_list");
  const deepseekUnsupported = methodDraft === "cli" && cliTypeDraft === "deepseek";
  const ready = Boolean(config) && !loading;
  const statusMessage = error
    ? { tone: "error" as const, text: error }
    : notice
      ? { tone: "success" as const, text: notice }
      : deepseekUnsupported
        ? { tone: "warning" as const, text: "DeepSeek Harness 暂不支持生成提交信息，请选择其他 CLI" }
        : null;
  const statusNode = statusMessage ? (
    <p
      role={statusMessage.tone === "error" ? "alert" : undefined}
      className={clsx(
        "min-w-0 flex-1 break-words text-[11px] leading-4",
        statusMessage.tone === "error" && "text-[var(--status-danger)]",
        statusMessage.tone === "success" && "text-[var(--status-success)]",
        statusMessage.tone === "warning" && "text-[var(--status-warning)]",
      )}
    >
      {statusMessage.text}
    </p>
  ) : null;

  function updateDraft(key: string, value: string | boolean) {
    setDraftValues((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <section
      data-testid="git-commit-cli-panel"
      className={clsx("space-y-2 text-xs", className)}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
        <h3 className="min-w-0 flex-1 truncate text-xs font-semibold">提交说明生成</h3>
        {ready ? (
          <div className={gitSegmentGroupClassName} role="group" aria-label="Commit Message 实现方式">
            {METHOD_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={methodDraft === option.value}
                onClick={() => setMethodDraft(option.value)}
                disabled={!canManage}
                className={gitSegmentClass(methodDraft === option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : null}
        <button
          type="button"
          aria-label="恢复默认"
          title="恢复默认"
          onClick={() => void reset()}
          disabled={!canManage || resetting || loading}
          className={gitIconButtonClassName}
        >
          {resetting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
        </button>
      </div>

      {disabledReason || !canManage ? (
        <p className="text-[11px] leading-4 text-[var(--muted)]">{disabledReason || "当前模式只读"}</p>
      ) : null}

      {loading ? (
        <p className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
          加载中...
        </p>
      ) : null}

      {ready ? (
        <>
          {methodDraft === "llm" ? (
            <p className="text-[11px] leading-4 text-[var(--muted)]">LLM API 复用管理中心的聊天翻译 API 配置。</p>
          ) : (
            <>
              <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-1.5">
                <label className="min-w-0 space-y-0.5">
                  <span className={fieldLabelClassName}>CLI 类型</span>
                  <select
                    aria-label="Commit Message CLI 类型"
                    value={cliTypeDraft}
                    disabled={!canManage}
                    onChange={(event) => {
                      const nextCliType = event.target.value as CliType;
                      setCliTypeDraft(nextCliType);
                      setCliPathDraft(defaultCliPathForType(nextCliType));
                    }}
                    className={gitInputClassName}
                  >
                    <option value="codex">codex</option>
                    <option value="codex_server">codex server</option>
                    <option value="claude">claude</option>
                    {cliTypeDraft === "deepseek" ? <option value="deepseek" disabled>DeepSeek Harness（暂不支持）</option> : null}
                  </select>
                </label>
                <label className="min-w-0 space-y-0.5">
                  <span className={fieldLabelClassName}>CLI 路径</span>
                  <input
                    aria-label="Commit Message CLI 路径"
                    value={cliPathDraft}
                    disabled={!canManage}
                    onChange={(event) => setCliPathDraft(event.target.value)}
                    placeholder={defaultCliPathForType(cliTypeDraft)}
                    className={clsx(gitInputClassName, "font-mono")}
                  />
                </label>
              </div>

              {fieldEntries.length > 0 ? (
                <div className="grid grid-cols-2 gap-1.5">
                  {fieldEntries.map(([key, field]) => {
                    const label = field.description || key;
                    const value = String(draftValues[key] ?? "");
                    const inputId = `git-commit-cli-param-${botAlias}-${key}`;
                    return (
                      <label key={key} htmlFor={inputId} className="min-w-0 space-y-0.5">
                        <span className={fieldLabelClassName} title={label}>{label}</span>
                        {field.enum ? (
                          <select
                            id={inputId}
                            aria-label={label}
                            value={value}
                            disabled={!canManage}
                            onChange={(event) => updateDraft(key, event.target.value)}
                            className={gitInputClassName}
                          >
                            {field.enum.map((item) => (
                              <option key={item} value={item}>{item}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            id={inputId}
                            aria-label={label}
                            type={field.type === "number" ? "number" : "text"}
                            value={value}
                            disabled={!canManage}
                            onChange={(event) => updateDraft(key, event.target.value)}
                            className={gitInputClassName}
                          />
                        )}
                      </label>
                    );
                  })}
                </div>
              ) : null}

              {booleanEntries.length > 0 ? (
                <div className="grid grid-cols-2 gap-x-2 gap-y-1">
                  {booleanEntries.map(([key, field]) => {
                    const label = field.description || key;
                    const inputId = `git-commit-cli-param-${botAlias}-${key}`;
                    return (
                      <label key={key} htmlFor={inputId} className="flex min-w-0 items-start gap-1.5 leading-4">
                        <input
                          id={inputId}
                          aria-label={label}
                          type="checkbox"
                          checked={Boolean(draftValues[key])}
                          disabled={!canManage}
                          onChange={(event) => updateDraft(key, event.target.checked)}
                          className="mt-px h-3.5 w-3.5 shrink-0 accent-[var(--accent)] disabled:opacity-60"
                        />
                        <span className="min-w-0 break-words">{label}</span>
                      </label>
                    );
                  })}
                </div>
              ) : null}

              {listEntries.map(([key, field]) => {
                const label = field.description || key;
                const inputId = `git-commit-cli-param-${botAlias}-${key}`;
                return (
                  <label key={key} htmlFor={inputId} className="block min-w-0 space-y-0.5">
                    <span className={fieldLabelClassName}>{label}</span>
                    <textarea
                      id={inputId}
                      aria-label={label}
                      rows={2}
                      value={String(draftValues[key] ?? "")}
                      disabled={!canManage}
                      placeholder="每行一个参数"
                      onChange={(event) => updateDraft(key, event.target.value)}
                      className={textareaClassName}
                    />
                  </label>
                );
              })}
            </>
          )}

          <div className="flex min-w-0 items-center gap-1.5">
            {statusNode ?? <span className="flex-1" />}
            <button
              type="button"
              onClick={() => void save()}
              disabled={!canManage || !hasChanges || saving}
              className={gitPrimaryButtonClassName}
            >
              {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {saving ? "保存中..." : "保存"}
            </button>
          </div>
        </>
      ) : statusNode}
    </section>
  );
}
