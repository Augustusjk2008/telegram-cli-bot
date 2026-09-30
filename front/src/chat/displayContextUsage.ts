import type { ChatMessage, ChatMessageContextUsage } from "../services/types";
import { mapEstimatedCost } from "../utils/contextUsage";
import { isCodexCli } from "../utils/cliType";

export function buildDisplayContextUsage(items: ChatMessage[]) {
  const result = new Map<string, ChatMessageContextUsage>();
  const previousByConversation = new Map<string, ChatMessageContextUsage | undefined>();
  for (const item of items) {
    if (item.role !== "assistant") continue;
    const usage = item.meta?.contextUsage;
    const conversation = item.conversationId || "";
    const previous = previousByConversation.get(conversation);
    previousByConversation.set(conversation, usage);
    if (!usage) continue;
    result.set(item.id, usage);
    if (!previous || !isCodexCli(usage.provider) || !isCodexCli(previous.provider)) continue;
    const cost = mapEstimatedCost(usage.estimatedCost);
    const previousCost = mapEstimatedCost(previous.estimatedCost);
    if (!cost || !previousCost || cost.currency !== previousCost.currency
      || cost.total <= previousCost.total) continue;
    if ((usage.provider === "codex_server" || usage.source?.startsWith("codex_server"))
      && cost.scope !== "session") continue;
    if ((previous.provider === "codex_server" || previous.source?.startsWith("codex_server"))
      && previousCost.scope !== "session") continue;
    // Codex session 金额是累计快照；仅显示总额作差，下一轮仍使用原始快照。
    result.set(item.id, {
      ...usage,
      estimatedCost: { ...cost, total: cost.total - previousCost.total },
    });
  }
  return result;
}
