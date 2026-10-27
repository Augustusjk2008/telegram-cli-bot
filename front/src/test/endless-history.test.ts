import { expect, test } from "vitest";
import { mergeEndlessHistoryMessages } from "../chat/endlessHistory";
import type { ChatMessage } from "../services/types";

function message(partial: Partial<ChatMessage> & Pick<ChatMessage, "id" | "role" | "text">): ChatMessage {
  return {
    createdAt: "2026-10-27T00:00:00Z",
    state: "done",
    ...partial,
  };
}

test("merges persisted endless continuation turns into one assistant row", () => {
  const items: ChatMessage[] = [
    message({ id: "user-1", role: "user", text: "原始问题", turnId: "turn-1" }),
    message({
      id: "assistant-1",
      role: "assistant",
      text: "第一次失败",
      state: "error",
      turnId: "turn-1",
      meta: {
        endlessGroupId: "group-1",
        endlessEvents: [{ kind: "error", sequence: 1, attempt: 0, text: "第一次失败" }],
      },
    }),
    message({ id: "user-2", role: "user", text: "Continue", turnId: "turn-2", meta: { endlessGroupId: "group-1" } }),
    message({
      id: "assistant-2",
      role: "assistant",
      text: "第二次失败",
      state: "error",
      turnId: "turn-2",
      meta: {
        endlessGroupId: "group-1",
        endlessEvents: [
          { kind: "error", sequence: 1, attempt: 1, text: "第二次失败" },
          { kind: "continue", sequence: 2, attempt: 1, text: "Continue" },
        ],
      },
    }),
    message({ id: "user-3", role: "user", text: "Continue", turnId: "turn-3", meta: { endlessGroupId: "group-1" } }),
    message({ id: "assistant-3", role: "assistant", text: "最终完成", turnId: "turn-3", meta: { endlessGroupId: "group-1", endlessContinueCount: 2 } }),
  ];

  const merged = mergeEndlessHistoryMessages(items);

  expect(merged).toHaveLength(2);
  expect(merged[1]).toMatchObject({ id: "assistant-3", text: "最终完成", turnId: "turn-3" });
  expect(merged[1].meta?.endlessEvents?.map((event) => event.text)).toEqual(["第一次失败", "第二次失败", "Continue"]);
  expect(merged[1].meta?.endlessContinueCount).toBe(2);
});

test("keeps an ordinary Continue turn separate", () => {
  const items = [
    message({ id: "user-1", role: "user", text: "问题", turnId: "turn-1" }),
    message({ id: "assistant-1", role: "assistant", text: "回答", turnId: "turn-1" }),
    message({ id: "user-2", role: "user", text: "Continue", turnId: "turn-2" }),
    message({ id: "assistant-2", role: "assistant", text: "补充回答", turnId: "turn-2" }),
  ];

  expect(mergeEndlessHistoryMessages(items)).toEqual(items);
});
