import type { ChatMessage, ChatMessageContextUsage, ChatMessageEstimatedCost } from "../services/types";
import { mapEstimatedCost } from "../utils/contextUsage";
import { isCodexCli } from "../utils/cliType";

type CodexCostState = {
  currency: string;
  /** Last session running total seen in the conversation, if any. */
  runningTotal?: number;
  /** Per-turn amounts shown since that running total; the next running total already includes them. */
  perTurnSince: number;
};

function isAppServer(usage: ChatMessageContextUsage) {
  return usage.provider === "codex_server" || Boolean(usage.source?.startsWith("codex_server"));
}

/**
 * Older Codex exec replies stored the session's running total; newer ones (`basis: "turn"`),
 * interrupted-turn estimates and app-server turns already hold one turn's own cost.
 */
function isRunningTotal(usage: ChatMessageContextUsage, cost: ChatMessageEstimatedCost) {
  if (cost.basis === "turn" || cost.isPartial) return false;
  return isAppServer(usage) ? cost.scope === "session" : true;
}

export function buildDisplayContextUsage(items: ChatMessage[]) {
  const result = new Map<string, ChatMessageContextUsage>();
  const states = new Map<string, CodexCostState>();
  for (const item of items) {
    if (item.role !== "assistant") continue;
    const usage = item.meta?.contextUsage;
    if (!usage) continue;
    result.set(item.id, usage);
    const conversation = item.conversationId || "";
    if (!isCodexCli(usage.provider)) {
      states.delete(conversation);
      continue;
    }
    const cost = mapEstimatedCost(usage.estimatedCost);
    // A stopped turn without a cost keeps the previous running total as the baseline.
    if (!cost) continue;
    let state = states.get(conversation);
    if (!state || state.currency !== cost.currency) {
      state = { currency: cost.currency, perTurnSince: 0 };
      states.set(conversation, state);
    }
    if (!isRunningTotal(usage, cost)) {
      state.perTurnSince += cost.total;
      continue;
    }
    const known = state.runningTotal !== undefined || state.perTurnSince > 0;
    const offset = (state.runningTotal ?? 0) + state.perTurnSince;
    if (known && cost.total > offset) {
      // Show only this turn's share; the stored running total stays the next baseline.
      result.set(item.id, { ...usage, estimatedCost: { ...cost, total: cost.total - offset } });
    }
    state.runningTotal = cost.total;
    state.perTurnSince = 0;
  }
  return result;
}
