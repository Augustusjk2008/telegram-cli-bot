import type { AgentSummary } from "../services/types";

type AgentSwitcherProps = {
  agents: AgentSummary[];
  activeAgentId: string;
  disabled?: boolean;
  onSelect: (agentId: string) => void;
};

export function AgentSwitcher({ agents, activeAgentId, disabled, onSelect }: AgentSwitcherProps) {
  if (agents.length <= 1) {
    return null;
  }
  const active = agents.find((item) => item.id === activeAgentId) || agents[0];

  return (
    <select
      aria-label="当前 agent"
      value={active.id}
      disabled={disabled}
      onChange={(event) => onSelect(event.target.value)}
      className="h-8 max-w-[12rem] shrink-0 truncate rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2.5 text-xs font-medium text-[var(--text)] hover:bg-[var(--workbench-hover-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60"
    >
      {agents.map((agent) => (
        <option key={agent.id} value={agent.id} disabled={!agent.enabled && agent.id !== active.id}>
          {agent.isProcessing ? "处理中 · " : ""}{agent.name}{!agent.enabled ? "（停用）" : ""}
        </option>
      ))}
    </select>
  );
}
