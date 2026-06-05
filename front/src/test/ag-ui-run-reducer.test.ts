import { describe, expect, test } from "vitest";
import { EventType } from "../services/agUiProtocol";
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
  });

  test("captures run error", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.RUN_ERROR,
      message: "boom",
      code: "bad",
    });
    expect(state.error).toEqual({ message: "boom", code: "bad" });
    expect(state.completed).toBe(true);
  });
});
