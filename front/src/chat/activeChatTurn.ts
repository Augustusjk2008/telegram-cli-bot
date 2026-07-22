import type { ChatMessage } from "../services/types";

export type ActiveAssistantTarget = {
  localAssistantId: string;
  assistantMessageId?: string;
  turnId?: string;
  streamStartedAtMs: number;
};

function normalized(value: string | undefined) {
  return String(value || "").trim();
}

export function findActiveAssistantIndex(
  items: readonly ChatMessage[],
  target: ActiveAssistantTarget,
) {
  const turnId = normalized(target.turnId);
  if (turnId) {
    const turnIndex = items.findIndex((item) => item.role === "assistant" && normalized(item.turnId) === turnId);
    if (turnIndex >= 0) {
      return turnIndex;
    }
  }

  const assistantMessageId = normalized(target.assistantMessageId);
  if (assistantMessageId) {
    const serverIdIndex = items.findIndex((item) => item.role === "assistant" && normalized(item.id) === assistantMessageId);
    if (serverIdIndex >= 0) {
      return serverIdIndex;
    }
  }

  const localAssistantId = normalized(target.localAssistantId);
  if (localAssistantId) {
    const localIdIndex = items.findIndex((item) => item.role === "assistant" && normalized(item.id) === localAssistantId);
    if (localIdIndex >= 0) {
      return localIdIndex;
    }
  }

  if (turnId || assistantMessageId) {
    return -1;
  }

  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role !== "assistant") {
      continue;
    }
    const createdAtMs = Date.parse(item.createdAt || "");
    const isRecent = !Number.isNaN(createdAtMs) && createdAtMs >= target.streamStartedAtMs - 1000;
    if (item.state === "streaming" || isRecent) {
      return index;
    }
  }
  return -1;
}

export function updateActiveAssistantMessage(
  items: ChatMessage[],
  target: ActiveAssistantTarget,
  updater: (item: ChatMessage) => ChatMessage,
) {
  const index = findActiveAssistantIndex(items, target);
  if (index < 0) {
    return items;
  }
  const current = items[index];
  const next = updater(current);
  if (next === current) {
    return items;
  }
  const nextItems = items.slice();
  nextItems[index] = next;
  return nextItems;
}

export function upsertActiveAssistantMessage(
  items: ChatMessage[],
  target: ActiveAssistantTarget,
  finalMessage: ChatMessage,
  merge: (current: ChatMessage, final: ChatMessage) => ChatMessage = (_current, final) => final,
) {
  const resolvedTarget: ActiveAssistantTarget = {
    ...target,
    assistantMessageId: target.assistantMessageId || finalMessage.id,
    turnId: target.turnId || finalMessage.turnId,
  };
  const index = findActiveAssistantIndex(items, resolvedTarget);
  if (index < 0) {
    return [...items, finalMessage];
  }
  const current = items[index];
  const next = merge(current, finalMessage);
  if (next === current) {
    return items;
  }
  const nextItems = items.slice();
  nextItems[index] = next;
  return nextItems;
}
