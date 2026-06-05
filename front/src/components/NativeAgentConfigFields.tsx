import type { NativeAgentConfigInput, NativeAgentDraft } from "../services/types";

type Props = {
  provider: string;
  model: string;
  opencodeAgent: string;
  baseUrl?: string;
  apiKey?: string;
  hasApiKey?: boolean;
  apiKeyMasked?: string;
  clearApiKey?: boolean;
  editing?: boolean;
  disabled: boolean;
  onNativeAgentChange: (patch: Partial<NativeAgentConfigInput & NativeAgentDraft>) => void;
};

export function NativeAgentConfigFields({
  provider,
  model,
  opencodeAgent,
  baseUrl = "",
  apiKey = "",
  hasApiKey = false,
  apiKeyMasked = "",
  clearApiKey = false,
  editing = false,
  disabled,
  onNativeAgentChange,
}: Props) {
  function updateProvider(value: string) {
    if (/^https?:\/\//i.test(value.trim())) {
      onNativeAgentChange({ provider: "codeflow", baseUrl: value.trim() });
      return;
    }
    onNativeAgentChange({ provider: value });
  }

  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="mb-3">
        <div className="text-sm font-medium">原生 agent 配置</div>
        <div className="mt-1 text-xs text-[var(--muted)]">配置 OpenCode provider、模型和连接信息。</div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">Provider</span>
          <input
            aria-label="原生 agent Provider"
            value={provider}
            disabled={disabled}
            onChange={(event) => updateProvider(event.target.value)}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            placeholder="codeflow"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">Model</span>
          <input
            aria-label="原生 agent Model"
            value={model}
            disabled={disabled}
            onChange={(event) => onNativeAgentChange({ model: event.target.value })}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            placeholder="gpt-5.1-codex"
          />
        </label>
        <label className="space-y-1 text-sm sm:col-span-2">
          <span className="text-[var(--muted)]">Base URL</span>
          <input
            aria-label="原生 agent Base URL"
            value={baseUrl}
            disabled={disabled}
            onChange={(event) => onNativeAgentChange({ baseUrl: event.target.value })}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            placeholder="https://cdn.codeflow.asia/v1"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">OpenCode agent</span>
          <input
            aria-label="OpenCode agent"
            value={opencodeAgent}
            disabled={disabled}
            onChange={(event) => onNativeAgentChange({ opencodeAgent: event.target.value })}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            placeholder="main"
          />
        </label>
        <div className="space-y-1 text-sm">
          <label className="space-y-1">
            <span className="text-[var(--muted)]">API Key</span>
            <input
              aria-label="原生 agent API Key"
              type="password"
              value={apiKey}
              disabled={disabled || clearApiKey}
              onChange={(event) => onNativeAgentChange({ apiKey: event.target.value, clearApiKey: false })}
              className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
              placeholder={editing && hasApiKey ? "留空保持已保存 key" : "sk-..."}
            />
          </label>
          {editing ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
              <span>{hasApiKey ? `已保存 ${apiKeyMasked || ""}`.trim() : "未保存"}</span>
              <button
                type="button"
                disabled={disabled || !hasApiKey}
                onClick={() => onNativeAgentChange({ apiKey: "", clearApiKey: true })}
                className="rounded-md border border-[var(--border)] px-2 py-1 hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                清除
              </button>
              {clearApiKey ? <span className="text-red-600">保存后清除</span> : null}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
