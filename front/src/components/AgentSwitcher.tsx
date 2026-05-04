import { Check, LoaderCircle } from "lucide-react";
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
    <div className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-1">
      {agents.slice(0, 4).map((agent) => {
        const selected = agent.id === active.id;
        return (
          <button
            key={agent.id}
            type="button"
            aria-label={`当前 agent：${agent.name}`}
            aria-pressed={selected}
            disabled={disabled || (!agent.enabled && !selected)}
            onClick={() => onSelect(agent.id)}
            className={selected
              ? "inline-flex h-8 max-w-[9rem] items-center gap-1.5 rounded-md bg-[var(--accent)] px-2.5 text-sm font-medium text-white disabled:opacity-60"
              : "inline-flex h-8 max-w-[9rem] items-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)] disabled:opacity-50"}
          >
            {agent.isProcessing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
            <span className="truncate">{agent.name}</span>
            {selected ? <Check className="h-3.5 w-3.5 shrink-0" /> : null}
          </button>
        );
      })}
      {agents.length > 4 ? (
        <select
          aria-label="更多 agent"
          value={active.id}
          disabled={disabled}
          onChange={(event) => onSelect(event.target.value)}
          className="h-8 max-w-[10rem] rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-sm"
        >
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id} disabled={!agent.enabled && agent.id !== active.id}>
              {agent.name}
            </option>
          ))}
        </select>
      ) : null}
    </div>
  );
}
