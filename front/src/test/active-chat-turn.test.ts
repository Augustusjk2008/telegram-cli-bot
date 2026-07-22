import { describe, expect, it } from "vitest";
import { upsertActiveAssistantMessage } from "../chat/activeChatTurn";
import type { ActiveAssistantTarget } from "../chat/activeChatTurn";
import type { ChatMessage } from "../services/types";

const target: ActiveAssistantTarget = {
  localAssistantId: "assistant-local",
  assistantMessageId: "assistant-server",
  turnId: "turn-1",
  streamStartedAtMs: Date.parse("2026-07-20T00:00:00Z"),
};

const finalMessage: ChatMessage = {
  id: "assistant-server",
  turnId: "turn-1",
  role: "assistant",
  text: "权威最终答复",
  createdAt: "2026-07-20T00:00:01Z",
  state: "done",
};

describe("upsertActiveAssistantMessage", () => {
  it("appends the authoritative final message when the active row disappeared", () => {
    expect(upsertActiveAssistantMessage([], target, finalMessage)).toEqual([finalMessage]);
  });

  it("replaces the local placeholder and remains idempotent when the final is applied twice", () => {
    const localPlaceholder: ChatMessage = {
      id: "assistant-local",
      role: "assistant",
      text: "处理中",
      createdAt: "2026-07-20T00:00:00Z",
      state: "streaming",
    };

    const first = upsertActiveAssistantMessage([localPlaceholder], target, finalMessage);
    const second = upsertActiveAssistantMessage(first, target, finalMessage);

    expect(first).toEqual([finalMessage]);
    expect(second).toEqual([finalMessage]);
  });
});
