import { expect, test } from "vitest";
import { mergeMessagesPreservingClientState } from "../screens/ChatScreen";
import type { ChatMessage, ChatMessageMetaInfo } from "../services/types";
import { mergeMessageMeta } from "../utils/chatMessageMeta";

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

test("server trace snapshot upgrades anonymous live events without doubling them", () => {
  const live: ChatMessageMetaInfo = {
    tracePresentation: "native_agent_flat",
    traceCount: 2,
    trace: [
      { kind: "commentary", summary: "同一过程", source: "native_agent", rawType: "message.text.reclassified" },
      { kind: "commentary", summary: "同一过程", source: "native_agent", rawType: "message.text.reclassified" },
    ],
  };
  const persisted: ChatMessageMetaInfo = {
    tracePresentation: "native_agent_flat",
    traceCount: 2,
    trace: [
      { id: "trace-1", ordinal: 1, kind: "commentary", summary: "同一过程", source: "native_agent", rawType: "message.text.reclassified" },
      { id: "trace-2", ordinal: 2, kind: "commentary", summary: "同一过程", source: "native_agent", rawType: "message.text.reclassified" },
    ],
  };
  const merged = mergeMessageMeta(live, persisted, undefined, { reconcileTraceSnapshots: true });

  expect(merged?.trace).toHaveLength(2);
  expect(merged?.trace?.map((item) => item.id)).toEqual(["trace-1", "trace-2"]);
});

test("trace snapshot load progress is independent from merged trace length", () => {
  const merged = mergeMessageMeta(
    {
      tracePresentation: "native_agent_flat",
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
