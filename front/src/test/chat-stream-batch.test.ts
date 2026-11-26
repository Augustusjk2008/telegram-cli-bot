import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useChatStreamBatcher } from "../hooks/useChatStreamBatcher";
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

  it("keeps interleaved assistant targets and their event order", () => {
    const other = { ...base, assistantId: "assistant-2" };
    const input: ChatStreamInputEvent[] = [
      { ...base, kind: "chunk", chunk: "a" },
      { ...other, kind: "chunk", chunk: "x" },
      { ...base, kind: "chunk", chunk: "b" },
      { ...other, kind: "trace", trace: { kind: "tool_result", summary: "tool" }, usingPreviewReplace: false },
      { ...other, kind: "chunk", chunk: "y" },
      { ...base, kind: "chunk", chunk: "c" },
    ];

    const batch = reduceChatStreamBatch(input);

    expect(batch.events.map((event) => `${event.kind}:${event.assistantId}`)).toEqual([
      "chunk:assistant-1",
      "chunk:assistant-2",
      "chunk:assistant-1",
      "trace:assistant-2",
      "chunk:assistant-2",
      "chunk:assistant-1",
    ]);
    expect(batch.events[0]).toMatchObject({ kind: "chunk", assistantId: "assistant-1", chunk: "a" });
    expect(batch.events[1]).toMatchObject({ kind: "chunk", assistantId: "assistant-2", chunk: "x" });
    expect(batch.events[2]).toMatchObject({ kind: "chunk", assistantId: "assistant-1", chunk: "b" });
    expect(batch.events[4]).toMatchObject({ kind: "chunk", assistantId: "assistant-2", chunk: "y" });
    expect(batch.events[5]).toMatchObject({ kind: "chunk", assistantId: "assistant-1", chunk: "c" });
  });

  it("keeps same-target status and trace events around text updates", () => {
    const input: ChatStreamInputEvent[] = [
      { ...base, kind: "chunk", chunk: "before" },
      { ...base, kind: "status", userMessageId: "user-1", status: { previewText: "preview" } },
      { ...base, kind: "chunk", chunk: "after-status" },
      { ...base, kind: "trace", trace: { kind: "tool_result", summary: "tool" }, usingPreviewReplace: false },
      { ...base, kind: "chunk", chunk: "after-trace" },
    ];

    const batch = reduceChatStreamBatch(input);

    expect(batch.events.map((event) => event.kind)).toEqual(["chunk", "status", "chunk", "trace", "chunk"]);
    expect(batch.events[0]).toMatchObject({ kind: "chunk", chunk: "before" });
    expect(batch.events[2]).toMatchObject({ kind: "chunk", chunk: "after-status" });
    expect(batch.events[4]).toMatchObject({ kind: "chunk", chunk: "after-trace" });
  });

  it("treats replaceText as a flush barrier", () => {
    const replaceEvent: ChatStreamInputEvent = {
      ...base,
      kind: "status",
      userMessageId: "user-1",
      status: { replaceText: "authoritative" },
    };

    expect(isChatStreamBarrier(replaceEvent)).toBe(true);

    const batch = reduceChatStreamBatch([
      { ...base, kind: "chunk", chunk: "old" },
      replaceEvent,
      { ...base, kind: "chunk", chunk: "tail" },
    ]);

    expect(batch.events.map((event) => event.kind)).toEqual(["chunk", "status", "chunk"]);
    expect(batch.events[0]).toMatchObject({ kind: "chunk", chunk: "old" });
    expect(batch.events[1]).toMatchObject({ kind: "status", status: { replaceText: "authoritative" } });
    expect(batch.events[2]).toMatchObject({ kind: "chunk", chunk: "tail" });
  });

  it("does not merge events across separately consumed batches", () => {
    const first = reduceChatStreamBatch([{ ...base, kind: "chunk", chunk: "a" }]);
    const second = reduceChatStreamBatch([{ ...base, kind: "chunk", chunk: "b" }]);

    expect(first.events).toHaveLength(1);
    expect(second.events).toHaveLength(1);
    expect(first.events[0]).toMatchObject({ kind: "chunk", chunk: "a" });
    expect(second.events[0]).toMatchObject({ kind: "chunk", chunk: "b" });
  });

  it("keeps immediate event delivery when frame batching is disabled", () => {
    const consume = vi.fn();
    const hook = renderHook(() => useChatStreamBatcher(consume, false));
    const first: ChatStreamInputEvent = { ...base, kind: "chunk", chunk: "a" };
    const second: ChatStreamInputEvent = { ...base, kind: "chunk", chunk: "b" };

    act(() => {
      hook.result.current.enqueue(first);
      hook.result.current.enqueue(second);
    });

    expect(consume.mock.calls).toEqual([[[first]], [[second]]]);
  });
});
