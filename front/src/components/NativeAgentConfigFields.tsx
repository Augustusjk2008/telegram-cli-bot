import type { NativeAgentConfigInput, NativeAgentDraft } from "../services/types";

type Props = {
  provider: string;
  model: string;
  piAgent: string;
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
  piAgent,
  baseUrl = "",
  apiKey = "",
  hasApiKey = false,
  apiKeyMasked = "",
  clearApiKey = false,
  editing = false,
  disabled,
  onNativeAgentChange,
}: Props) {
  void provider;
  void model;
  void baseUrl;
  void apiKey;
  void hasApiKey;
  void apiKeyMasked;
  void clearApiKey;
  void editing;

  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="mb-3">
        <div className="text-sm font-medium">原生 agent</div>
        <div className="mt-1 text-xs text-[var(--muted)]">Provider、模型、Base URL、API Key 和推理参数在全局环境配置中设置。</div>
      </div>
      <div className="grid grid-cols-1 gap-3">
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">Pi agent</span>
          <input
            aria-label="Pi agent"
            value={piAgent}
            disabled={disabled}
            onChange={(event) => onNativeAgentChange({ piAgent: event.target.value })}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            placeholder="main"
          />
        </label>
      </div>
    </section>
  );
}
