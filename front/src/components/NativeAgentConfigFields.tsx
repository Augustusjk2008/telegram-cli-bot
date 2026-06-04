import type { NativeAgentConfig } from "../services/types";

type Props = {
  provider: string;
  model: string;
  opencodeAgent: string;
  disabled: boolean;
  onNativeAgentChange: (patch: Partial<NativeAgentConfig>) => void;
};

export function NativeAgentConfigFields({
  provider,
  model,
  opencodeAgent,
  disabled,
  onNativeAgentChange,
}: Props) {
  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="mb-3">
        <div className="text-sm font-medium">原生 agent 配置</div>
        <div className="mt-1 text-xs text-[var(--muted)]">仅配置模型提供方、模型和 OpenCode agent。</div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-[var(--muted)]">Provider</span>
          <input
            aria-label="原生 agent Provider"
            value={provider}
            disabled={disabled}
            onChange={(event) => onNativeAgentChange({ provider: event.target.value })}
            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            placeholder="anthropic"
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
            placeholder="claude-sonnet-4-5"
          />
        </label>
        <label className="space-y-1 text-sm sm:col-span-2">
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
      </div>
    </section>
  );
}
