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

  test("does not append legacy done output after direct ag-ui text", () => {
    const adapter = createAgUiStreamAdapter();
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
    const adapter = createAgUiStreamAdapter();
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
});
