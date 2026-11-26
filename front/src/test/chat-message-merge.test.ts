import { expect, test } from "vitest";
import { applyChatStreamEvents, mergeMessagesPreservingClientState } from "../screens/ChatScreen";
import type { ChatMessage } from "../services/types";
import type { ChatStreamRenderEvent } from "../stream/chatStreamBatch";
import { compactCompletedMessageMeta, mergeMessageMeta } from "../utils/chatMessageMeta";

const streamBase = { sendVersion: 1, streamStartedAtMs: 100 };

function streamingAssistant(id: string): ChatMessage {
  return {
    id,
    role: "assistant",
    text: "",
    createdAt: "2026-07-07T10:00:01Z",
    state: "streaming",
  };
}

function applyStreamEvents(items: ChatMessage[], events: readonly ChatStreamRenderEvent[]) {
  return applyChatStreamEvents(items, events, streamBase.sendVersion);
}

test("stream batching applies one coalesced text update per assistant target", () => {
  const merged = applyStreamEvents(
    [streamingAssistant("assistant-1"), streamingAssistant("assistant-2")],
    [
      { ...streamBase, assistantId: "assistant-1", kind: "chunk", chunk: "first" },
      { ...streamBase, assistantId: "assistant-2", kind: "chunk", chunk: "other" },
      { ...streamBase, assistantId: "assistant-1", kind: "chunk", chunk: " answer" },
    ],
  );

  expect(merged.map((item) => item.text)).toEqual(["first answer", "other"]);
});

test("stream text batching crosses non-text events without changing their order", () => {
  const merged = applyStreamEvents(
    [streamingAssistant("assistant-1")],
    [
      { ...streamBase, assistantId: "assistant-1", kind: "chunk", chunk: "before" },
      {
        ...streamBase,
        assistantId: "assistant-1",
        kind: "status",
        userMessageId: "user-1",
        status: { elapsedSeconds: 1 },
      },
      {
        ...streamBase,
        assistantId: "assistant-1",
        kind: "trace",
        trace: { kind: "tool_result", summary: "tool" },
        usingPreviewReplace: false,
      },
      { ...streamBase, assistantId: "assistant-1", kind: "chunk", chunk: " after" },
    ],
  );

  expect(merged[0].text).toBe("before after");
  expect(merged[0].meta?.trace).toEqual([{ kind: "tool_result", summary: "tool" }]);
});

test("stream status and trace previews stay ordered around text updates", () => {
  const merged = applyStreamEvents(
    [streamingAssistant("assistant-1")],
    [
      {
        ...streamBase,
        assistantId: "assistant-1",
        kind: "status",
        userMessageId: "user-1",
        status: { previewText: "preview " },
      },
      {
        ...streamBase,
        assistantId: "assistant-1",
        kind: "chunk",
        chunk: "answer",
      },
    ],
  );

  expect(merged[0].text).toBe("preview answer");

  const tracePreview = applyStreamEvents(
    [streamingAssistant("assistant-1")],
    [
      {
        ...streamBase,
        assistantId: "assistant-1",
        kind: "trace",
        trace: { kind: "commentary", summary: "thinking " },
        usingPreviewReplace: false,
      },
      {
        ...streamBase,
        assistantId: "assistant-1",
        kind: "chunk",
        chunk: "answer",
      },
    ],
  );

  expect(tracePreview[0].text).toBe("thinking answer");
});

test("replaceText remains a text barrier for subsequent chunks", () => {
  const merged = applyStreamEvents(
    [streamingAssistant("assistant-1")],
    [
      { ...streamBase, assistantId: "assistant-1", kind: "chunk", chunk: "old" },
      {
        ...streamBase,
        assistantId: "assistant-1",
        kind: "status",
        userMessageId: "user-1",
        status: { replaceText: "authoritative" },
      },
      { ...streamBase, assistantId: "assistant-1", kind: "chunk", chunk: " tail" },
    ],
  );

  expect(merged[0].text).toBe("authoritative tail");
});

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

test("persisted message revisions reuse the previous object and its loaded metadata", () => {
  const previous: ChatMessage = {
    id: "assistant-revisioned",
    revision: 7,
    role: "assistant",
    text: "已完成",
    createdAt: "2026-07-07T10:00:01Z",
    state: "done",
    meta: {
      traceCount: 3,
      traceLoadedCount: 3,
      trace: [{ id: "trace-1", kind: "tool_result", summary: "完整结果", payload: { output: "large" } }],
    },
  };
  const incoming: ChatMessage = {
    ...previous,
    meta: { traceCount: 3, traceLoadedCount: 1 },
  };

  const merged = mergeMessagesPreservingClientState([previous], [incoming]);

  expect(merged[0]).toBe(previous);
  expect(merged[0].meta).toBe(previous.meta);
});

test("a newer persisted message revision accepts the incoming content", () => {
  const previous: ChatMessage = {
    id: "assistant-revisioned",
    revision: 7,
    role: "assistant",
    text: "旧内容",
    createdAt: "2026-07-07T10:00:01Z",
    state: "done",
  };
  const incoming: ChatMessage = {
    ...previous,
    revision: 8,
    text: "新内容",
  };

  const merged = mergeMessagesPreservingClientState([previous], [incoming]);

  expect(merged[0]).not.toBe(previous);
  expect(merged[0].text).toBe("新内容");
  expect(merged[0].revision).toBe(8);
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

test("history merge keeps multiple user messages in one turn distinct", () => {
  const previousItems: ChatMessage[] = [
    {
      id: "user-original",
      turnId: "turn-steered",
      role: "user",
      text: "原始问题",
      createdAt: "2026-09-30T06:00:00Z",
      state: "done",
    },
    {
      id: "user-steer",
      turnId: "turn-steered",
      role: "user",
      text: "追加要求",
      createdAt: "2026-09-30T06:00:01Z",
      state: "done",
    },
    {
      id: "assistant-steered",
      turnId: "turn-steered",
      role: "assistant",
      text: "完成",
      createdAt: "2026-09-30T06:00:02Z",
      state: "done",
    },
  ];

  const merged = mergeMessagesPreservingClientState(previousItems, previousItems.map((item) => ({ ...item })));

  expect(merged.map((item) => item.id)).toEqual(["user-original", "user-steer", "assistant-steered"]);
});

test("trace snapshot load progress is independent from merged trace length", () => {
  const merged = mergeMessageMeta(
    {
      tracePresentation: "generic",
      traceCount: 8,
      traceLoadedCount: 4,
      trace: Array.from({ length: 12 }, (_, index) => ({
        id: `mixed-${index}`,
        kind: "commentary",
        summary: `过程 ${index}`,
      })),
    },
    { traceCount: 9, traceLoadedCount: 9 },
  );

  expect(merged?.trace).toHaveLength(12);
  expect(merged?.traceCount).toBe(9);
  expect(merged?.traceLoadedCount).toBe(9);
});

test("completed message compaction releases full trace payloads but preserves summaries", () => {
  const compact = compactCompletedMessageMeta({
    completionState: "completed",
    tracePresentation: "generic",
    traceLoadedCount: 2,
    trace: [
      {
        id: "trace-1",
        kind: "commentary",
        summary: "过程",
        payload: { output: "live-only-large-payload" },
      },
      {
        id: "trace-2",
        kind: "tool_call",
        toolName: "shell_command",
        summary: "dir",
        payload: { arguments: { command: "dir" } },
      },
    ],
  });

  expect(compact?.trace).toBeUndefined();
  expect(compact?.traceLoadedCount).toBeUndefined();
  expect(compact).toMatchObject({
    completionState: "completed",
    traceCount: 2,
    toolCallCount: 1,
    processCount: 1,
    tracePresentation: "generic",
  });
});

test("message metadata keeps endless events, timestamps, and Continue count across streaming merges", () => {
  const merged = mergeMessageMeta(
    {
      endlessEvents: [{ kind: "error", sequence: 9, attempt: 1, text: "临时失败", createdAt: "2026-10-31T00:00:02Z" }],
      endlessContinueCount: 0,
    },
    {
      endlessEvents: [
        { kind: "continue", sequence: 4, attempt: 1, text: "Continue", createdAt: "2026-10-31T00:00:03Z" },
        { kind: "error", sequence: 1, attempt: 1, text: "临时失败" },
      ],
      endlessContinueCount: 1,
    },
  );

  expect(merged?.endlessEvents?.map((event) => event.kind)).toEqual(["error", "continue"]);
  expect(merged?.endlessEvents?.[0]?.sequence).toBe(1);
  expect(merged?.endlessEvents?.[0]?.createdAt).toBe("2026-10-31T00:00:02Z");
  expect(merged?.endlessContinueCount).toBe(1);
  expect(compactCompletedMessageMeta(merged)?.endlessEvents).toEqual(merged?.endlessEvents);
  expect(compactCompletedMessageMeta(merged)?.endlessContinueCount).toBe(1);
});

test("completed trace metadata excludes the duplicated final commentary from process count", () => {
  const compact = compactCompletedMessageMeta({
    completionState: "completed",
    trace: [
      { kind: "commentary", summary: "分析完成" },
      { kind: "commentary", summary: "最终回答" },
    ],
    processCount: 2,
  }, "最终回答");

  expect(compact?.processCount).toBe(1);
});
