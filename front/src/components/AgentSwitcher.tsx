import { LoaderCircle } from "lucide-react";
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
  const shellClassName = disabled
    ? "inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 text-sm font-medium text-[var(--text)] opacity-60"
    : "inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 text-sm font-medium text-[var(--text)] hover:bg-[var(--surface-strong)]";

  return (
    <div className={shellClassName}>
      {active.isProcessing ? (
        <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-[var(--accent)]" />
      ) : null}
      <div className="relative">
        <select
          aria-label="当前 agent"
          value={active.id}
          disabled={disabled}
          onChange={(event) => onSelect(event.target.value)}
          className="h-full min-w-[8rem] max-w-[14rem] appearance-none bg-transparent pr-6 text-sm font-medium text-[var(--text)] outline-none"
        >
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id} disabled={!agent.enabled && agent.id !== active.id}>
              {agent.isProcessing ? "处理中 · " : ""}{agent.name}{!agent.enabled ? "（停用）" : ""}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
