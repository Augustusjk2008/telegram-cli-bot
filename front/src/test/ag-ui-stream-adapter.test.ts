import { describe, expect, test } from "vitest";
import { EventType } from "../services/agUiProtocol";
import { createAgUiStreamAdapter } from "../services/agUiStreamAdapter";

describe("agUiStreamAdapter", () => {
  test("parses ag-ui events and filters heartbeat", () => {
    const adapter = createAgUiStreamAdapter();
    expect(adapter.adapt({ type: "server.heartbeat" })).toEqual([]);
    expect(adapter.adapt({
      type: EventType.TEXT_MESSAGE_CONTENT,
      messageId: "msg-1",
      delta: "hello",
    })).toEqual([expect.objectContaining({
      type: EventType.TEXT_MESSAGE_CONTENT,
      messageId: "msg-1",
      delta: "hello",
    })]);
  });

  test("ignores legacy stream events by default", () => {
    const adapter = createAgUiStreamAdapter();
    expect(adapter.adapt({ type: "status", elapsed_seconds: 1, preview_text: "处理中" })).toEqual([]);
    expect(adapter.adapt({ type: "trace", event: { kind: "commentary", summary: "检查目录" } })).toEqual([]);
    expect(adapter.adapt({ type: "done", output: "ok" })).toEqual([]);
  });

  test("bridges legacy done output when enabled", () => {
    const adapter = createAgUiStreamAdapter({ bridgeLegacy: true });
    const events = [
      ...adapter.adapt({ type: EventType.TEXT_MESSAGE_START, messageId: "msg-1", role: "assistant" }),
      ...adapter.adapt({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: "msg-1", delta: "internal thinking" }),
      ...adapter.adapt({ type: "done", output: "ok" }),
    ];

    expect(events.map((item) => item.type)).toEqual([
      EventType.TEXT_MESSAGE_START,
      EventType.TEXT_MESSAGE_CONTENT,
      EventType.TEXT_MESSAGE_END,
      EventType.RUN_FINISHED,
    ]);
  });

  test("maps legacy stream events to ag-ui sequence", () => {
    const adapter = createAgUiStreamAdapter({ bridgeLegacy: true });
    const events = [
      ...adapter.adapt({ type: "meta", cluster_run_id: "clr_1" }),
      ...adapter.adapt({ type: "status", elapsed_seconds: 2, preview_text: "处理中" }),
      ...adapter.adapt({ type: "trace", event: {
        kind: "tool_call",
        tool_name: "shell",
        call_id: "call_1",
        summary: "",
        payload: {
          arguments: {
            command: "dir",
          },
        },
      } }),
      ...adapter.adapt({ type: "delta", text: "ok" }),
      ...adapter.adapt({ type: "trace", event: {
        kind: "permission",
        source: "native_agent",
        summary: "请求读取文件",
        payload: {
          id: "perm-1",
          state: "permission.updated",
        },
      } }),
      ...adapter.adapt({ type: "done", output: "ok" }),
    ];

    expect(events.map((item) => item.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.ACTIVITY_SNAPSHOT,
      EventType.ACTIVITY_SNAPSHOT,
      EventType.TOOL_CALL_START,
      EventType.TOOL_CALL_ARGS,
      EventType.TOOL_CALL_END,
      EventType.TEXT_MESSAGE_START,
      EventType.TEXT_MESSAGE_CONTENT,
      EventType.ACTIVITY_SNAPSHOT,
      EventType.TEXT_MESSAGE_END,
      EventType.RUN_FINISHED,
    ]);
    expect(events[1]).toEqual(expect.objectContaining({
      type: EventType.ACTIVITY_SNAPSHOT,
      activityType: "TCB_META",
      content: expect.objectContaining({ clusterRunId: "clr_1" }),
    }));
    expect(events[8]).toEqual(expect.objectContaining({
      type: EventType.ACTIVITY_SNAPSHOT,
      activityType: "TCB_PERMISSION_REQUEST",
      content: expect.objectContaining({ id: "perm-1" }),
    }));
  });

  test("maps legacy snapshot to message snapshot", () => {
    const adapter = createAgUiStreamAdapter({ bridgeLegacy: true });
    const events = [
      ...adapter.adapt({ type: "delta", text: "先查一下..." }),
      ...adapter.adapt({ type: "snapshot", text: "" }),
      ...adapter.adapt({ type: "delta", text: "最终答复" }),
    ];

    expect(events.map((item) => item.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.TEXT_MESSAGE_START,
      EventType.TEXT_MESSAGE_CONTENT,
      EventType.MESSAGES_SNAPSHOT,
      EventType.TEXT_MESSAGE_CONTENT,
    ]);
    expect(events[3]).toEqual(expect.objectContaining({
      type: EventType.MESSAGES_SNAPSHOT,
      messages: [expect.objectContaining({
        role: "assistant",
        content: "",
      })],
    }));
  });

  test("uses legacy snapshot field when text is absent", () => {
    const adapter = createAgUiStreamAdapter({ bridgeLegacy: true });
    const events = adapter.adapt({ type: "snapshot", snapshot: "最终快照" });

    expect(events).toEqual([
      expect.objectContaining({ type: EventType.RUN_STARTED }),
      expect.objectContaining({
        type: EventType.MESSAGES_SNAPSHOT,
        messages: [expect.objectContaining({ content: "最终快照" })],
      }),
    ]);
  });

  test("preserves legacy trace stable ordering metadata", () => {
    const adapter = createAgUiStreamAdapter({ bridgeLegacy: true });
    const events = adapter.adapt({
      type: "trace",
      event: {
        id: "trace-1",
        ordinal: 7,
        created_at: "2026-06-06T00:00:00Z",
        kind: "commentary",
        source: "native_agent",
        summary: "先检查目录。",
      },
    });

    expect(events).toEqual([
      expect.objectContaining({ type: EventType.RUN_STARTED }),
      expect.objectContaining({
        type: EventType.ACTIVITY_SNAPSHOT,
        content: expect.objectContaining({
          id: "trace-1",
          ordinal: 7,
          createdAt: "2026-06-06T00:00:00Z",
          rawKind: "commentary",
        }),
      }),
    ]);
  });
});
