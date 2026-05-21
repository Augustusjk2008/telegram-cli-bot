import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Save } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  CliParamField,
  CliType,
  GitCommitMessageCliConfig,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { defaultCliPathForType } from "../screens/useBotManager";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  canManage?: boolean;
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

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function GitCommitCliConfigPanel({
  botAlias,
  client = new MockWebBotClient(),
  canManage = true,
  className = "",
}: Props) {
  const [config, setConfig] = useState<GitCommitMessageCliConfig | null>(null);
  const [draftValues, setDraftValues] = useState<DraftValues>({});
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
    void client.getGitCommitMessageConfig(botAlias)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setConfig(payload);
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
  }, [botAlias, client]);

  const entries = useMemo(() => Object.entries(config?.schema || {}), [config]);
  const baseDrafts = useMemo(() => (config ? buildDraftValues(config) : {}), [config]);
  const hasChanges = useMemo(() => {
    if (!config) {
      return false;
    }
    if (cliTypeDraft !== config.cliType || cliPathDraft !== config.cliPath) {
      return true;
    }
    return entries.some(([key]) => baseDrafts[key] !== (draftValues[key] ?? ""));
  }, [baseDrafts, cliPathDraft, cliTypeDraft, config, draftValues, entries]);

  async function save() {
    if (!config || !canManage) {
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
        cliType: cliTypeDraft,
        cliPath: cliPathDraft.trim(),
        ...(Object.keys(nextParams).length > 0 ? { params: nextParams } : {}),
      });
      setConfig(next);
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

  return (
    <section
      data-testid="git-commit-cli-panel"
      className={`space-y-3 ${className}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Commit Message CLI</h2>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {canManage ? "全局生成提交说明配置" : "当前模式只读"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void save()}
            disabled={!canManage || !hasChanges || saving || loading}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-[var(--accent)] px-2.5 text-xs font-medium text-[var(--accent-foreground)] hover:opacity-90 disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {saving ? "保存中..." : "保存"}
          </button>
          <button
            type="button"
            onClick={() => void reset()}
            disabled={!canManage || resetting || loading}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 text-xs font-medium hover:bg-[var(--surface-strong)] disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {resetting ? "重置中..." : "恢复默认"}
          </button>
        </div>
      </div>

      {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      {notice ? <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div> : null}
      {loading ? <div className="text-xs text-[var(--muted)]">加载中...</div> : null}

      {!loading ? (
        <>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs font-medium text-[var(--muted)]">CLI 类型</span>
              <select
                aria-label="Commit Message CLI 类型"
                value={cliTypeDraft}
                disabled={!canManage}
                onChange={(event) => {
                  const nextCliType = event.target.value as CliType;
                  setCliTypeDraft(nextCliType);
                  setCliPathDraft(defaultCliPathForType(nextCliType));
                }}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm disabled:opacity-60"
              >
                <option value="codex">codex</option>
                <option value="claude">claude</option>
                <option value="kimi">kimi</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs font-medium text-[var(--muted)]">CLI 路径</span>
              <input
                aria-label="Commit Message CLI 路径"
                value={cliPathDraft}
                disabled={!canManage}
                onChange={(event) => setCliPathDraft(event.target.value)}
                placeholder={defaultCliPathForType(cliTypeDraft)}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm disabled:opacity-60"
              />
            </label>
          </div>

          <div className="grid gap-2 md:grid-cols-2">
            {entries.map(([key, field]) => {
              const label = field.description || key;
              const value = draftValues[key] ?? "";
              const inputId = `git-commit-cli-param-${botAlias}-${key}`;
              if (field.type === "boolean") {
                return (
                  <label
                    key={key}
                    htmlFor={inputId}
                    className="flex items-center justify-between gap-4 rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
                  >
                    <span>{label}</span>
                    <input
                      id={inputId}
                      aria-label={label}
                      type="checkbox"
                      checked={Boolean(value)}
                      disabled={!canManage}
                      onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.checked }))}
                      className="h-4 w-4"
                    />
                  </label>
                );
              }
              return (
                <label key={key} className="space-y-1">
                  <span className="text-xs font-medium text-[var(--muted)]">{label}</span>
                  {field.enum ? (
                    <select
                      id={inputId}
                      aria-label={label}
                      value={String(value)}
                      disabled={!canManage}
                      onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                      className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm disabled:opacity-60"
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
                      className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm disabled:opacity-60"
                    />
                  ) : (
                    <input
                      id={inputId}
                      aria-label={label}
                      type={field.type === "number" ? "number" : "text"}
                      value={String(value)}
                      disabled={!canManage}
                      onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                      className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm disabled:opacity-60"
                    />
                  )}
                </label>
              );
            })}
          </div>
        </>
      ) : null}
    </section>
  );
}
