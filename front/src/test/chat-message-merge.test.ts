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
