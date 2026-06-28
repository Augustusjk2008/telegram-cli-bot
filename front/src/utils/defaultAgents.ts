import type { AgentSummary } from "../services/types";

export function fallbackAgents(): AgentSummary[] {
  return [{ id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true }];
}
