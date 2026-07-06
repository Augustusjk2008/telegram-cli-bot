import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { toolbarButtonClass } from "./ToolbarButton";
import type { InlineCompletionConfig, InlineCompletionConfigInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";

type Props = {
  client: WebBotClient;
  onSaved?: () => void;
  onError?: (message: string) => void;
};

type Draft = InlineCompletionConfig & {
  apiKey: string;
  clearApiKey: boolean;
};

const EMPTY_CONFIG: InlineCompletionConfig = {
  enabled: false,
  providerType: "openai_compatible",
  baseUrl: "",
  apiKeySet: false,
  configured: false,
  model: "",
  temperature: 0.2,
  maxOutputTokens: 96,
  requestTimeoutSeconds: 8,
  autoTriggerEnabled: true,
  autoTriggerDelayMs: 700,
  manualTriggerEnabled: true,
  maxPrefixChars: 16000,
  maxSuffixChars: 4000,
  maxRelatedFiles: 4,
  maxRelatedFileBytes: 4096,
  denyGlobs: [".env*", "managed_bots.json", "*.pem", "*.key", ".git/**", "node_modules/**", "dist/**", "build/**"],
};

function draftFromConfig(config: InlineCompletionConfig): Draft {
  return {
    ...config,
    denyGlobs: [...config.denyGlobs],
    apiKey: "",
    clearApiKey: false,
  };
}

function numberInputValue(value: number) {
  return Number.isFinite(value) ? String(value) : "";
}

export function AiInlineCompletionSettingsPanel({ client, onSaved, onError }: Props) {
  const [draft, setDraft] = useState<Draft>(() => draftFromConfig(EMPTY_CONFIG));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLocalError("");
    void client.getInlineCompletionConfig()
      .then((config) => {
        if (!cancelled) {
          setDraft(draftFromConfig(config));
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLocalError(getErrorMessage(error, "加载 AI inline 补全配置失败"));
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
  }, [client]);

  const updateDraft = <Key extends keyof Draft>(key: Key, value: Draft[Key]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const updateNumberDraft = (key: keyof Pick<Draft,
    "temperature"
    | "maxOutputTokens"
    | "requestTimeoutSeconds"
    | "autoTriggerDelayMs"
    | "maxPrefixChars"
    | "maxSuffixChars"
    | "maxRelatedFiles"
    | "maxRelatedFileBytes"
  >, value: string) => {
    const numeric = key === "temperature" ? Number.parseFloat(value) : Number.parseInt(value, 10);
    setDraft((prev) => ({ ...prev, [key]: Number.isFinite(numeric) ? numeric : 0 }));
  };

  const save = async () => {
    const input: InlineCompletionConfigInput = {
      enabled: draft.enabled,
      providerType: draft.providerType,
      baseUrl: draft.baseUrl.trim(),
      model: draft.model.trim(),
      temperature: draft.temperature,
      maxOutputTokens: draft.maxOutputTokens,
      requestTimeoutSeconds: draft.requestTimeoutSeconds,
      autoTriggerEnabled: draft.autoTriggerEnabled,
      autoTriggerDelayMs: draft.autoTriggerDelayMs,
      manualTriggerEnabled: draft.manualTriggerEnabled,
      maxPrefixChars: draft.maxPrefixChars,
      maxSuffixChars: draft.maxSuffixChars,
      maxRelatedFiles: draft.maxRelatedFiles,
      maxRelatedFileBytes: draft.maxRelatedFileBytes,
      denyGlobs: draft.denyGlobs,
      ...(draft.apiKey.trim() ? { apiKey: draft.apiKey.trim() } : {}),
      ...(draft.clearApiKey ? { clearApiKey: true } : {}),
    };
    setSaving(true);
    setLocalError("");
    try {
      const next = await client.updateInlineCompletionConfig(input);
      setDraft(draftFromConfig(next));
      onSaved?.();
    } catch (error) {
      const message = getErrorMessage(error, "保存 AI inline 补全配置失败");
      setLocalError(message);
      onError?.(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-4 shadow-[var(--shadow-soft)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-[var(--text)]">AI inline 补全（全局）</h2>
        <span className="rounded-md border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted)]">
          {draft.configured ? "已配置" : "未配置"}
        </span>
      </div>

      {loading ? <div className="text-sm text-[var(--muted)]">加载中...</div> : null}
      {localError ? <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{localError}</div> : null}

      <div className="space-y-4">
        <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
          <span className="text-sm text-[var(--text)]">启用 AI inline 补全</span>
          <input
            aria-label="启用 AI inline 补全"
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) => updateDraft("enabled", event.target.checked)}
            className="h-4 w-4"
          />
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">服务地址</span>
            <input
              aria-label="服务地址"
              value={draft.baseUrl}
              onChange={(event) => updateDraft("baseUrl", event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">模型</span>
            <input
              aria-label="模型"
              value={draft.model}
              onChange={(event) => updateDraft("model", event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">API 密钥</span>
            <input
              aria-label="API 密钥"
              type="password"
              value={draft.apiKey}
              placeholder={draft.apiKeySet ? "已保存" : ""}
              onChange={(event) => updateDraft("apiKey", event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
            />
          </label>

          <label className="flex items-end gap-2 pb-2 text-sm text-[var(--text)]">
            <input
              aria-label="清除 API Key"
              type="checkbox"
              checked={draft.clearApiKey}
              onChange={(event) => updateDraft("clearApiKey", event.target.checked)}
              className="h-4 w-4"
            />
            清除 API Key
          </label>
        </div>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">温度</span>
            <input aria-label="温度" type="number" step="0.1" value={numberInputValue(draft.temperature)} onChange={(event) => updateNumberDraft("temperature", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">最大输出 token</span>
            <input aria-label="最大输出 token" type="number" value={numberInputValue(draft.maxOutputTokens)} onChange={(event) => updateNumberDraft("maxOutputTokens", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">自动延迟 ms</span>
            <input aria-label="自动延迟 ms" type="number" value={numberInputValue(draft.autoTriggerDelayMs)} onChange={(event) => updateNumberDraft("autoTriggerDelayMs", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">超时秒数</span>
            <input aria-label="超时秒数" type="number" value={numberInputValue(draft.requestTimeoutSeconds)} onChange={(event) => updateNumberDraft("requestTimeoutSeconds", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">前缀字符上限</span>
            <input aria-label="前缀字符上限" type="number" value={numberInputValue(draft.maxPrefixChars)} onChange={(event) => updateNumberDraft("maxPrefixChars", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">后缀字符上限</span>
            <input aria-label="后缀字符上限" type="number" value={numberInputValue(draft.maxSuffixChars)} onChange={(event) => updateNumberDraft("maxSuffixChars", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">关联文件数</span>
            <input aria-label="关联文件数" type="number" value={numberInputValue(draft.maxRelatedFiles)} onChange={(event) => updateNumberDraft("maxRelatedFiles", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">关联文件字节</span>
            <input aria-label="关联文件字节" type="number" value={numberInputValue(draft.maxRelatedFileBytes)} onChange={(event) => updateNumberDraft("maxRelatedFileBytes", event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]" />
          </label>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
            <span className="text-sm text-[var(--text)]">自动触发</span>
            <input aria-label="自动触发" type="checkbox" checked={draft.autoTriggerEnabled} onChange={(event) => updateDraft("autoTriggerEnabled", event.target.checked)} className="h-4 w-4" />
          </label>
          <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
            <span className="text-sm text-[var(--text)]">手动触发</span>
            <input aria-label="手动触发" type="checkbox" checked={draft.manualTriggerEnabled} onChange={(event) => updateDraft("manualTriggerEnabled", event.target.checked)} className="h-4 w-4" />
          </label>
        </div>

        <label className="space-y-2">
          <span className="text-sm font-medium text-[var(--text)]">排除路径规则</span>
          <textarea
            aria-label="排除路径规则"
            value={draft.denyGlobs.join("\n")}
            onChange={(event) => updateDraft("denyGlobs", event.target.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean))}
            rows={4}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm text-[var(--text)]"
          />
        </label>

        <button
          type="button"
          onClick={() => void save()}
          disabled={loading || saving}
          className={toolbarButtonClass("primary", "md")}
        >
          <Save className="h-4 w-4" />
          {saving ? "保存中..." : "保存 AI inline 补全配置"}
        </button>
      </div>
    </div>
  );
}
