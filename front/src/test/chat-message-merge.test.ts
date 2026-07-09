import { expect, test } from "vitest";
import { mergeMessagesPreservingClientState } from "../screens/ChatScreen";
import type { ChatMessage } from "../services/types";

test("idle history merge preserves message references when nothing changed", () => {
  const previousItems: ChatMessage[] = [
    {
      id: "user-1",
      role: "user",
      text: "旧消息",
      createdAt: "2026-07-07T10:00:00Z",
      state: "done",
    },
    {
      id: "assistant-1",
      role: "assistant",
      text: "# 长回复\n\n".repeat(200),
      createdAt: "2026-07-07T10:00:01Z",
      state: "done",
      elapsedSeconds: 3,
      meta: {
        traceCount: 0,
      },
    },
  ];
  const nextItems = previousItems.map((item) => ({ ...item }));

  const merged = mergeMessagesPreservingClientState(previousItems, nextItems);

  expect(merged).toBe(previousItems);
  expect(merged[0]).toBe(previousItems[0]);
  expect(merged[1]).toBe(previousItems[1]);
});

test("history merge deduplicates reset rows already represented locally", () => {
  const previousItems: ChatMessage[] = [
    {
      id: "user-1",
      role: "user",
      text: "修复刷新",
      createdAt: "2026-07-07T10:00:00Z",
      state: "done",
    },
    {
      id: "assistant-local-final",
      role: "assistant",
      text: "最终回复",
      createdAt: "2026-07-07T10:00:01Z",
      state: "done",
    },
    {
      id: "user-1",
      role: "user",
      text: "修复刷新",
      createdAt: "2026-07-07T10:00:00Z",
      state: "done",
    },
    {
      id: "assistant-history-final",
      role: "assistant",
      text: "最终回复",
      createdAt: "2026-07-07T10:00:01Z",
      state: "done",
    },
  ];

  const merged = mergeMessagesPreservingClientState(previousItems, previousItems);

  expect(merged.map((item) => item.id)).toEqual(["user-1", "assistant-history-final"]);
  expect(merged[0]).toBe(previousItems[0]);
  expect(merged[1]).not.toBe(previousItems[1]);
});
