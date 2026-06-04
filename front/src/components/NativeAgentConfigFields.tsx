import type { ChatExecutionMode, NativeAgentConfig } from "../services/types";

type Props = {
  enabled: boolean;
  defaultMode: ChatExecutionMode;
  command: string;
  hostname: string;
  port: number;
  serverPassword?: string;
  disabled: boolean;
  onEnabledChange: (value: boolean) => void;
  onDefaultModeChange: (value: ChatExecutionMode) => void;
  onNativeAgentChange: (patch: Partial<NativeAgentConfig>) => void;
};

export function NativeAgentConfigFields({
  enabled,
  defaultMode,
  command,
  hostname,
  port,
  serverPassword,
  disabled,
  onEnabledChange,
  onDefaultModeChange,
  onNativeAgentChange,
}: Props) {
  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="inline-flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={enabled}
            disabled={disabled}
            onChange={(event) => {
              const checked = event.target.checked;
              onEnabledChange(checked);
              if (!checked) {
                onDefaultModeChange("cli");
              }
            }}
          />
          启用原生 agent
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-[var(--muted)]">默认</span>
          <select
            aria-label="默认执行模式"
            value={enabled ? defaultMode : "cli"}
            disabled={disabled || !enabled}
            onChange={(event) => onDefaultModeChange(event.target.value as ChatExecutionMode)}
            className="h-8 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-sm disabled:opacity-60"
          >
            <option value="cli">CLI</option>
            <option value="native_agent">原生 agent</option>
          </select>
        </label>
      </div>
      {enabled ? (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-[var(--muted)]">命令</span>
            <input
              aria-label="原生 agent 命令"
              value={command}
              disabled={disabled}
              onChange={(event) => onNativeAgentChange({ command: event.target.value })}
              className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
              placeholder="opencode"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-[var(--muted)]">Host</span>
            <input
              aria-label="原生 agent Host"
              value={hostname}
              disabled={disabled}
              onChange={(event) => onNativeAgentChange({ hostname: event.target.value })}
              className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
              placeholder="127.0.0.1"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-[var(--muted)]">端口</span>
            <input
              aria-label="原生 agent 端口"
              type="number"
              min={0}
              max={65535}
              value={port}
              disabled={disabled}
              onChange={(event) => onNativeAgentChange({ port: Number(event.target.value || 0) })}
              className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-[var(--muted)]">密码</span>
            <input
              aria-label="原生 agent 服务密码"
              type="password"
              value={serverPassword || ""}
              disabled={disabled}
              onChange={(event) => onNativeAgentChange({ serverPassword: event.target.value })}
              className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm disabled:opacity-60"
              placeholder="留空保留/自动生成"
            />
          </label>
        </div>
      ) : null}
    </section>
  );
}
