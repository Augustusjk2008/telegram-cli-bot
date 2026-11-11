import { describe, expect, it } from "vitest";
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
      { ...base, kind: "trace", trace: { kind: "commentary", summary: "one" }, usingPreviewReplace: false },
      { ...base, kind: "trace", trace: { kind: "commentary", summary: "two" }, usingPreviewReplace: false },
    ];

    const batch = reduceChatStreamBatch(input);

    expect(batch.events.map((event) => event.kind)).toEqual(["chunk", "status", "trace", "trace"]);
    expect(batch.events[0]).toMatchObject({ kind: "chunk", chunk: "ab" });
    expect(batch.events[1]).toMatchObject({
      kind: "status",
      status: { previewText: "last", elapsedSeconds: 2 },
    });
    expect(batch.events.slice(2).map((event) => event.kind === "trace" ? event.trace.summary : "")).toEqual(["one", "two"]);
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
