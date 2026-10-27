import type { ChatEndlessEvent, ChatMessage, ChatMessageMetaInfo } from "../services/types";
import { mergeMessageMeta } from "../utils/chatMessageMeta";

function endlessEventKey(event: ChatEndlessEvent) {
  return [event.kind, event.attempt, event.code || "", event.text].join("\u0000");
}

function mergeGroupMeta(items: ChatMessage[], groupId: string): ChatMessageMetaInfo {
  let merged: ChatMessageMetaInfo | undefined;
  const events: ChatEndlessEvent[] = [];
  const seenEvents = new Set<string>();
  let continueCount = 0;
  for (const item of items) {
    merged = mergeMessageMeta(merged, item.meta);
    continueCount = Math.max(continueCount, item.meta?.endlessContinueCount || 0);
    for (const event of item.meta?.endlessEvents || []) {
      const normalized: ChatEndlessEvent = {
        kind: event.kind,
        sequence: events.length + 1,
        attempt: Math.max(0, Math.floor(event.attempt || 0)),
        text: String(event.text || "").trim(),
        ...(event.code ? { code: event.code } : {}),
      };
      if (!normalized.text || seenEvents.has(endlessEventKey(normalized))) {
        continue;
      }
      seenEvents.add(endlessEventKey(normalized));
      events.push(normalized);
    }
  }
  continueCount = Math.max(continueCount, events.filter((event) => event.kind === "continue").length);
  return {
    ...(merged || {}),
    endlessGroupId: groupId,
    ...(events.length > 0 ? { endlessEvents: events } : {}),
    ...(continueCount > 0 || typeof merged?.endlessContinueCount === "number"
      ? { endlessContinueCount: continueCount }
      : {}),
  };
}

/** Collapse persisted turns from one endless run into the same row used by live streaming. */
export function mergeEndlessHistoryMessages(items: readonly ChatMessage[]): ChatMessage[] {
  const groups = new Map<string, number[]>();
  items.forEach((item, index) => {
    const groupId = item.meta?.endlessGroupId?.trim();
    if (!groupId) {
      return;
    }
    groups.set(groupId, [...(groups.get(groupId) || []), index]);
  });
  if (groups.size === 0) {
    return [...items];
  }

  const replacements = new Map<number, ChatMessage>();
  const removed = new Set<number>();
  for (const [groupId, indexes] of groups) {
    const assistantIndexes = indexes.filter((index) => items[index].role === "assistant");
    if (assistantIndexes.length < 2) {
      continue;
    }
    const assistantItems = assistantIndexes.map((index) => items[index]);
    const primary = assistantItems[assistantItems.length - 1];
    const first = assistantItems[0];
    const text = [...assistantItems].reverse().find((item) => item.text.trim())?.text || "";
    const mergedItem: ChatMessage = {
      ...primary,
      createdAt: first.createdAt || primary.createdAt,
      text,
      meta: mergeGroupMeta(assistantItems, groupId),
    };
    replacements.set(assistantIndexes[0], mergedItem);
    assistantIndexes.slice(1).forEach((index) => removed.add(index));
    const userIndexes = indexes.filter((index) => items[index].role === "user");
    const hasGroupedRootUser = userIndexes.some((index) => index < assistantIndexes[0]);
    (hasGroupedRootUser ? userIndexes.slice(1) : userIndexes).forEach((index) => removed.add(index));
  }

  if (replacements.size === 0) {
    return [...items];
  }
  const result: ChatMessage[] = [];
  items.forEach((item, index) => {
    if (removed.has(index)) {
      return;
    }
    result.push(replacements.get(index) || item);
  });
  return result;
}
