import { describe, expect, test } from "vitest";
import { EventType, type AgUiEvent } from "../services/agUiProtocol";
import { createAgUiStreamAdapter } from "../services/agUiStreamAdapter";
import {
  buildAgUiMessageMeta,
  createAgUiRunAccumulator,
  createAgUiRunState,
  reduceAgUiRunEvent,
} from "../utils/agUiRunReducer";

describe("agUiRunReducer", () => {
  test("deduplicates anonymous native activity replays", () => {
    const event = {
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-replay",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        summary: "重复过程",
        source: "native",
        rawKind: "commentary",
        rawType: "message.text.reclassified",
      },
    } as const;

    const state = [event, event].reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.traceEvents).toHaveLength(1);
    expect(state.entries).toHaveLength(1);
  });

  test("marks source=native activities as native transcript content", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "legacy-message-1",
      activityType: "TCB_TRACE_COMMENTARY",
      replace: true,
      content: {
        summary: "原生过程",
        source: "native",
        rawKind: "commentary",
      },
    });

    expect(state.nativeAgent).toBe(true);
    expect(buildAgUiMessageMeta(state)?.tracePresentation).toBe("native_agent_flat");
  });

  test("folds cumulative anonymous native activity commentary", () => {
    const events = [
      ["我先", "message.text.reclassified"],
      ["我先检查目录。", "assistant_message"],
      ["我先检查目录。", "message.text.reclassified"],
    ].map(([summary, rawType]) => ({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-cumulative",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        summary,
        source: "native",
        rawKind: "commentary",
        rawType,
      },
    } as const));

    const state = events.reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.traceEvents).toHaveLength(1);
    expect(state.entries).toHaveLength(1);
    expect(state.entries[0]?.summary).toBe("我先检查目录。");
  });

  test("does not use the legacy adapter placeholder as an activity identity", () => {
    const adapter = createAgUiStreamAdapter({ bridgeLegacy: true });
    const events = ["过程一", "过程一", "过程二"].flatMap((summary) => adapter.adapt({
      type: "trace",
      event: {
        kind: "commentary",
        summary,
        source: "native",
        raw_type: "message.text.reclassified",
      },
    }));

    const state = events.reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.traceEvents.map((trace) => trace.summary)).toEqual(["过程一", "过程二"]);
  });

  test("incremental accumulator preserves reducer trace and transcript behavior", () => {
    const events = [
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-later",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          id: "trace-later",
          ordinal: 20,
          summary: "稍后过程",
          source: "native_agent",
          rawKind: "commentary",
          rawType: "message.text.reclassified",
        },
      },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-earlier",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          id: "trace-earlier",
          ordinal: 10,
          summary: "较早过程",
          source: "native_agent",
          rawKind: "commentary",
          rawType: "message.text.reclassified",
        },
      },
      {
        type: EventType.TOOL_CALL_START,
        toolCallId: "call-1",
        toolCallName: "shell_command",
      },
      {
        type: EventType.TOOL_CALL_ARGS,
        toolCallId: "call-1",
        delta: "{\"command\":",
      },
      {
        type: EventType.TOOL_CALL_ARGS,
        toolCallId: "call-1",
        delta: "\"dir\"}",
      },
      {
        type: EventType.TOOL_CALL_RESULT,
        messageId: "tool-result-1",
        toolCallId: "call-1",
        content: "partial",
      },
      {
        type: EventType.TOOL_CALL_RESULT,
        messageId: "tool-result-1",
        toolCallId: "call-1",
        content: "final",
      },
    ] as const;

    const expected = events.reduce(reduceAgUiRunEvent, createAgUiRunState());
    const accumulator = createAgUiRunAccumulator();
    for (const event of events) {
      accumulator.reduce(event);
    }
    const actual = accumulator.snapshot();

    expect(buildAgUiMessageMeta(actual)).toEqual(buildAgUiMessageMeta(expected));
    expect(actual.traceEvents.map((trace) => trace.ordinal)).toEqual(expected.traceEvents.map((trace) => trace.ordinal));
    expect(actual.entries.map((entry) => entry.summary)).toEqual(expected.entries.map((entry) => entry.summary));
  });

  test("incremental accumulator preserves activity identity behavior when a delta adds an id", () => {
    const events: AgUiEvent[] = [
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-1",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          summary: "初始过程",
          source: "native_agent",
          rawKind: "commentary",
          rawType: "message.text.reclassified",
        },
      },
      {
        type: EventType.ACTIVITY_DELTA,
        messageId: "activity-1",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        patch: [
          { op: "add", path: "/id", value: "trace-1" },
          { op: "replace", path: "/summary", value: "更新后的过程" },
        ],
      },
    ];

    const expected = events.reduce(reduceAgUiRunEvent, createAgUiRunState());
    const accumulator = createAgUiRunAccumulator();
    const actual = accumulator.reduce(events);

    expect(actual.activities).toEqual(expected.activities);
    expect(actual.entries).toEqual(expected.entries);
  });

  test("incremental accumulator matches the reducer across a representative native run", () => {
    const events: AgUiEvent[] = [
      { type: EventType.RUN_STARTED, threadId: "thread-1", runId: "run-1" },
      { type: EventType.TEXT_MESSAGE_START, messageId: "assistant-1", role: "assistant" },
      { type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-1", delta: "最终" },
      { type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-1", delta: "回答" },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "status-1",
        activityType: "TCB_STATUS",
        replace: true,
        content: {
          id: "status-1",
          message: "正在处理",
          source: "native_agent",
          elapsedSeconds: 2,
        },
      },
      {
        type: EventType.ACTIVITY_DELTA,
        messageId: "status-1",
        activityType: "TCB_STATUS",
        patch: [{ op: "replace", path: "/message", value: "即将完成" }],
      },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "permission-1",
        activityType: "TCB_PERMISSION_REQUEST",
        replace: true,
        content: {
          id: "permission-1",
          permissionId: "permission-1",
          summary: "允许执行命令",
          source: "codex",
          uiKind: "confirm",
          state: "pending",
        },
      },
      {
        type: EventType.ACTIVITY_DELTA,
        messageId: "permission-1",
        activityType: "TCB_PERMISSION_REQUEST",
        patch: [{ op: "replace", path: "/state", value: "approved" }],
      },
      { type: EventType.TOOL_CALL_START, toolCallId: "call-1", toolCallName: "shell_command" },
      { type: EventType.TOOL_CALL_ARGS, toolCallId: "call-1", delta: "{\"command\":" },
      { type: EventType.TOOL_CALL_ARGS, toolCallId: "call-1", delta: "\"dir\"}" },
      { type: EventType.TOOL_CALL_END, toolCallId: "call-1" },
      {
        type: EventType.TOOL_CALL_RESULT,
        messageId: "tool-result-1",
        toolCallId: "call-1",
        content: "完成",
        role: "tool",
      },
      { type: EventType.REASONING_MESSAGE_START, messageId: "reasoning-1", role: "reasoning" },
      { type: EventType.REASONING_MESSAGE_CONTENT, messageId: "reasoning-1", delta: "分析" },
      { type: EventType.REASONING_MESSAGE_CONTENT, messageId: "reasoning-1", delta: "完成" },
      { type: EventType.REASONING_MESSAGE_END, messageId: "reasoning-1" },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "meta-1",
        activityType: "TCB_META",
        replace: true,
        content: { clusterRunId: "cluster-1" },
      },
      {
        type: EventType.RUN_FINISHED,
        threadId: "thread-1",
        runId: "run-1",
        outcome: { type: "success" },
        result: { completion_state: "completed", elapsedSeconds: 3 },
      },
    ];

    const expected = events.reduce(reduceAgUiRunEvent, createAgUiRunState());
    const accumulator = createAgUiRunAccumulator();
    const actual = accumulator.reduce(events);

    expect(actual).toEqual(expected);
    expect(buildAgUiMessageMeta(actual)).toEqual(buildAgUiMessageMeta(expected));
  });

  test("incremental accumulator keeps trace work linear across single-event batches", () => {
    const run = (count: number) => {
      const accumulator = createAgUiRunAccumulator();
      accumulator.reduce({
        type: EventType.TOOL_CALL_START,
        toolCallId: "initial-tool",
        toolCallName: "shell_command",
      });
      for (let index = 0; index < count; index += 1) {
        accumulator.reduce({
          type: EventType.ACTIVITY_SNAPSHOT,
          messageId: `activity-${index}`,
          activityType: "TCB_NATIVE_AGENT_TRACE",
          replace: true,
          content: {
            id: `trace-${index}`,
            ordinal: index + 1,
            summary: `过程 ${index}`,
            source: "native_agent",
            rawKind: "commentary",
            rawType: "message.text.reclassified",
          },
        });
      }
      const snapshot = accumulator.snapshot();
      return { diagnostics: accumulator.diagnostics(), snapshot };
    };

    const small = run(1_000);
    const large = run(5_000);

    expect(large.snapshot.traceEvents).toHaveLength(5_001);
    expect(large.snapshot.entries).toHaveLength(5_001);
    expect(large.snapshot.traceEvents[0]?.ordinal).toBe(1);
    expect(large.snapshot.traceEvents.at(-1)?.kind).toBe("tool_call");
    expect(large.diagnostics.indexBuilds).toBeLessThanOrEqual(3);
    expect(large.diagnostics.fullScanItems).toBeLessThanOrEqual(128);
    expect(large.diagnostics.lookupProbes).toBeLessThanOrEqual(8 * 5_000 + 128);
    expect(large.diagnostics.materializedArraySlots).toBeLessThanOrEqual(12 * 5_000 + 512);
    expect(large.diagnostics.lookupProbes).toBeLessThanOrEqual(small.diagnostics.lookupProbes * 6);
    expect(large.diagnostics.materializedArraySlots).toBeLessThanOrEqual(
      small.diagnostics.materializedArraySlots * 6,
    );
  });

  test("incremental accumulator bounds anonymous native trace lookup work", () => {
    const run = (count: number) => {
      const accumulator = createAgUiRunAccumulator();
      for (let index = 0; index < count; index += 1) {
        accumulator.reduce({
          type: EventType.ACTIVITY_SNAPSHOT,
          messageId: "legacy-message-performance",
          activityType: "TCB_NATIVE_AGENT_TRACE",
          replace: true,
          content: {
            summary: `独立过程 ${String(index).padStart(5, "0")}`,
            source: "native_agent",
            rawKind: "commentary",
            rawType: "assistant_message",
          },
        });
      }
      return {
        diagnostics: accumulator.diagnostics(),
        snapshot: accumulator.snapshot(),
      };
    };

    const small = run(256);
    const large = run(1_024);

    expect(large.snapshot.traceEvents).toHaveLength(1_024);
    expect(large.snapshot.entries).toHaveLength(1_024);
    expect(large.diagnostics.fullScanItems).toBeLessThanOrEqual(128);
    expect(large.diagnostics.lookupProbes).toBeLessThanOrEqual(24 * 1_024 + 128);
    expect(large.diagnostics.lookupProbes).toBeLessThanOrEqual(small.diagnostics.lookupProbes * 5);
  });

  test("dispose releases incremental indexes without changing the final snapshot", () => {
    const accumulator = createAgUiRunAccumulator();
    accumulator.reduce({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-1",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        id: "trace-1",
        summary: "过程",
        source: "native_agent",
        rawKind: "commentary",
      },
    });
    const finalSnapshot = accumulator.snapshot();

    accumulator.dispose();
    accumulator.dispose();

    expect(accumulator.diagnostics()).toMatchObject({
      disposed: true,
      indexedEntries: 0,
    });
    expect(finalSnapshot.traceEvents).toHaveLength(1);
    expect(finalSnapshot.entries).toHaveLength(1);
  });

  test("dispose does not erase state already exposed to the live transcript", () => {
    const accumulator = createAgUiRunAccumulator();
    const liveState = accumulator.reduce({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-live",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        id: "trace-live",
        summary: "仍在显示的过程",
        source: "native_agent",
        rawKind: "commentary",
      },
    });

    accumulator.dispose();

    expect(liveState.traceEvents).toHaveLength(1);
    expect(liveState.entries).toHaveLength(1);
    expect(buildAgUiMessageMeta(liveState)?.trace?.[0]?.summary).toBe("仍在显示的过程");
  });
});
