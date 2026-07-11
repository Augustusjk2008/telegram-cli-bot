import { describe, expect, it, vi } from "vitest";
import { createAgUiRunState, reduceAgUiRunEvent } from "../utils/agUiRunReducer";
import { EventType, type AgUiEvent } from "../services/agUiProtocol";
import type { ChatStreamInputEvent } from "../stream/chatStreamBatch";
import { isChatStreamBarrier, reduceChatStreamBatch } from "../stream/chatStreamBatch";

const base = { sendVersion: 1, assistantId: "assistant-1", streamStartedAtMs: 100 };

describe("chat stream domain batching", () => {
  it("joins consecutive text, keeps trace order, and uses the latest status fields", () => {
    const input: ChatStreamInputEvent[] = [
      { ...base, kind: "chunk", chunk: "a" },
      { ...base, kind: "chunk", chunk: "b" },
      { ...base, kind: "status", userMessageId: "user-1", status: { previewText: "first" } },
      { ...base, kind: "status", userMessageId: "user-1", status: { previewText: "last", elapsedSeconds: 2 } },
      { ...base, kind: "trace", trace: { kind: "commentary", summary: "one" }, nativeTrace: false, usingPreviewReplace: false },
      { ...base, kind: "trace", trace: { kind: "commentary", summary: "two" }, nativeTrace: false, usingPreviewReplace: false },
    ];

    const batch = reduceChatStreamBatch(input, null);

    expect(batch.events.map((event) => event.kind)).toEqual(["chunk", "status", "trace", "trace"]);
    expect(batch.events[0]).toMatchObject({ kind: "chunk", chunk: "ab" });
    expect(batch.events[1]).toMatchObject({
      kind: "status",
      status: { previewText: "last", elapsedSeconds: 2 },
    });
    expect(batch.events.slice(2).map((event) => event.kind === "trace" ? event.trace.summary : "")).toEqual(["one", "two"]);
  });

  it("reduces a run of AG-UI deltas to one render event", () => {
    const agUi = (delta: string): ChatStreamInputEvent => ({
      ...base,
      kind: "ag_ui",
      nativeAgent: true,
      event: { type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-1", delta } as AgUiEvent,
    });

    const reduceBatch = vi.fn((state, events: readonly AgUiEvent[]) => events.reduce(
      (current, event) => reduceAgUiRunEvent(current, event),
      state || createAgUiRunState(),
    ));
    const batch = reduceChatStreamBatch([agUi("hello"), agUi(" world")], null, reduceBatch);

    expect(reduceBatch).toHaveBeenCalledTimes(1);
    expect(batch.sawAgUiEvent).toBe(true);
    expect(batch.events).toHaveLength(1);
    expect(batch.events[0]).toMatchObject({ kind: "ag_ui", state: { assistantText: "hello world" } });
  });

  it("treats replaceText as a flush barrier", () => {
    expect(isChatStreamBarrier({
      ...base,
      kind: "status",
      userMessageId: "user-1",
      status: { replaceText: "authoritative" },
    })).toBe(true);
  });
});
