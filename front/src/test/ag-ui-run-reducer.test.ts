import { describe, expect, test } from "vitest";
import { EventType, type AgUiEvent } from "../services/agUiProtocol";
import {
  buildAgUiMessageMeta,
  createAgUiRunState,
  reduceAgUiRunEvent,
} from "../utils/agUiRunReducer";

describe("agUiRunReducer", () => {
  test("builds assistant text and trace from ag-ui events", () => {
    const events = [
      {
        type: EventType.RUN_STARTED,
        threadId: "thread-1",
        runId: "run-1",
      },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "msg-1",
        activityType: "TCB_STATUS",
        replace: true,
        content: {
          elapsedSeconds: 2,
          previewText: "处理中",
          contextUsage: {
            session_id: "thread-ctx",
            status_text: "74% context left",
          },
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
        delta: "{\"command\":\"dir\"}",
      },
      {
        type: EventType.TOOL_CALL_RESULT,
        messageId: "msg-1",
        toolCallId: "call-1",
        content: "Exit code: 0",
      },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "msg-1",
        activityType: "TCB_PERMISSION_REQUEST",
        replace: true,
        content: {
          id: "perm-1",
          state: "permission.updated",
          summary: "请求读取文件",
          source: "native_agent",
        },
      },
      {
        type: EventType.TEXT_MESSAGE_START,
        messageId: "msg-1",
        role: "assistant",
      },
      {
        type: EventType.TEXT_MESSAGE_CONTENT,
        messageId: "msg-1",
        delta: "hello",
      },
      {
        type: EventType.TEXT_MESSAGE_CONTENT,
        messageId: "msg-1",
        delta: " world",
      },
      {
        type: EventType.RUN_FINISHED,
        threadId: "thread-1",
        runId: "run-1",
        outcome: { type: "success" },
      },
    ] as const;

    const state = events.reduce(reduceAgUiRunEvent, createAgUiRunState());
    expect(state.assistantText).toBe("hello world");
    expect(state.previewText).toBe("处理中");
    expect(state.toolCalls).toEqual([expect.objectContaining({
      toolCallId: "call-1",
      toolCallName: "shell_command",
      argsText: "{\"command\":\"dir\"}",
      resultText: "Exit code: 0",
      status: "completed",
    })]);
    expect(state.permissionRequests).toEqual([expect.objectContaining({
      permissionId: "perm-1",
      summary: "请求读取文件",
    })]);
    expect(state.completed).toBe(true);

    const meta = buildAgUiMessageMeta(state);
    expect(meta?.traceCount).toBe(4);
    expect(meta?.toolCallCount).toBe(1);
    expect(meta?.processCount).toBe(2);
    expect(meta?.contextUsage?.sessionId).toBe("thread-ctx");
    expect(state.entries.map((entry) => entry.kind)).toEqual(["process", "tool", "event", "permission"]);
    expect(state.entries.map((entry) => entry.summary)).toEqual([
      "处理中",
      "shell_command",
      "Exit code: 0",
      "请求读取文件",
    ]);
  });

  test("captures run error", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.RUN_ERROR,
      message: "boom",
      code: "bad",
    });
    expect(state.error).toEqual({ message: "boom", code: "bad" });
    expect(state.completed).toBe(true);
    expect(state.entries.at(-1)).toEqual(expect.objectContaining({
      kind: "error",
      summary: "boom",
    }));
  });

  test("does not infer native flat presentation from session error alone", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.RUN_ERROR,
      message: "OpenCode failed",
      code: "session.error",
    });

    expect(buildAgUiMessageMeta(state)?.tracePresentation).toBeUndefined();
  });

  test("captures cancelled run finish as interrupt trace", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.RUN_FINISHED,
      threadId: "thread-1",
      runId: "run-1",
      outcome: {
        type: "interrupt",
        interrupts: [{ id: "interrupt-1", reason: "cancelled" }],
      },
    });

    expect(state.completed).toBe(true);
    const meta = buildAgUiMessageMeta(state);
    expect(meta?.completionState).toBe("cancelled");
    expect(meta?.trace).toEqual([
      expect.objectContaining({ kind: "cancelled", summary: "用户终止输出" }),
    ]);
    expect(state.entries.at(-1)).toEqual(expect.objectContaining({
      kind: "cancelled",
      summary: "用户终止输出",
    }));
  });

  test("replaces assistant text from message snapshot", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.MESSAGES_SNAPSHOT,
      messages: [
        { id: "user-1", role: "user", content: "hi" },
        { id: "assistant-1", role: "assistant", content: "ok" },
      ],
    });

    expect(state.messageId).toBe("assistant-1");
    expect(state.assistantText).toBe("ok");
  });

  test("clears assistant text from empty message snapshot", () => {
    const withText = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.TEXT_MESSAGE_CONTENT,
      messageId: "assistant-1",
      delta: "先查一下...",
    });
    const state = reduceAgUiRunEvent(withText, {
      type: EventType.MESSAGES_SNAPSHOT,
      messages: [
        { id: "assistant-1", role: "assistant", content: "" },
      ],
    });

    expect(state.messageId).toBe("assistant-1");
    expect(state.assistantText).toBe("");
  });

  test("keeps multiple native trace activities visible", () => {
    const events: AgUiEvent[] = [
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-1",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          summary: "读取目录",
          rawKind: "tool_call",
          rawType: "message.part.updated",
        },
      },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-2",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          summary: "写入文件",
          rawKind: "tool_call",
          rawType: "message.part.updated",
        },
      },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-3",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          summary: "测试通过",
          rawKind: "tool_result",
          rawType: "message.part.updated",
        },
      },
    ];
    const state = events.reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.activities.map((activity) => activity.summary)).toEqual([
      "读取目录",
      "写入文件",
      "测试通过",
    ]);
    expect(state.traceEvents.map((event) => event.kind)).toEqual([
      "tool_call",
      "tool_call",
      "tool_result",
    ]);
    expect(state.entries.map((entry) => entry.summary)).toEqual([
      "读取目录",
      "写入文件",
      "测试通过",
    ]);
  });

  test("keeps duplicate native trace entries append-only", () => {
    const events: AgUiEvent[] = [
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-1",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          summary: "重复过程",
          rawKind: "commentary",
          rawType: "message.text.reclassified",
        },
      },
      {
        type: EventType.ACTIVITY_SNAPSHOT,
        messageId: "activity-2",
        activityType: "TCB_NATIVE_AGENT_TRACE",
        replace: true,
        content: {
          summary: "重复过程",
          rawKind: "commentary",
          rawType: "message.text.reclassified",
        },
      },
    ];

    const state = events.reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.entries).toHaveLength(2);
    expect(buildAgUiMessageMeta(state)?.trace).toEqual([
      expect.objectContaining({ kind: "commentary", summary: "重复过程", sequence: 1 }),
      expect.objectContaining({ kind: "commentary", summary: "重复过程", sequence: 2 }),
    ]);
  });

  test("does not mark handled native permissions as pending", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-perm-1",
      activityType: "TCB_PERMISSION_REQUEST",
      replace: true,
      content: {
        id: "perm-1",
        permissionId: "perm-1",
        summary: "原生 agent 权限已允许",
        state: "permission.replied",
        source: "native_agent",
      },
    });

    expect(state.permissionRequests).toEqual([expect.objectContaining({
      permissionId: "perm-1",
      state: "permission.replied",
    })]);
    expect(state.entries).toEqual([expect.objectContaining({
      kind: "permission",
      permissionId: "perm-1",
      pending: false,
    })]);
  });

  test("does not infer native flat presentation from non-native permission activity", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-perm-2",
      activityType: "TCB_PERMISSION_REQUEST",
      replace: true,
      content: {
        id: "perm-2",
        permissionId: "perm-2",
        summary: "CLI 请求确认",
        state: "permission.updated",
        source: "codex",
      },
    });

    expect(state.entries).toEqual([expect.objectContaining({
      kind: "permission",
      permissionId: "perm-2",
    })]);
    expect(buildAgUiMessageMeta(state)?.tracePresentation).toBeUndefined();
  });
});
