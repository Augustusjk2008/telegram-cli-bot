import { describe, expect, test } from "vitest";
import type { ChatTraceEvent } from "../services/types";
import { groupChatTraceEntries, parseToolResultStatus } from "../utils/chatTraceGrouping";

function toolCall(callId: string, summary: string): ChatTraceEvent {
  return {
    kind: "tool_call",
    toolName: "shell_command",
    callId,
    summary,
    payload: {
      arguments: {
        command: summary,
      },
    },
  };
}

function toolResult(callId: string, summary: string): ChatTraceEvent {
  return {
    kind: "tool_result",
    callId,
    summary,
    payload: {
      output: summary,
    },
  };
}

describe("groupChatTraceEntries", () => {
  test("pairs tool_call and tool_result by callId", () => {
    const entries = groupChatTraceEntries([
      { kind: "commentary", summary: "准备读取" },
      toolCall("call_1", "Get-Content a.txt"),
      toolResult("call_1", "Exit code: 0\nWall time: 1.1 seconds\nOutput:\nok"),
      { kind: "commentary", summary: "读取完成" },
    ]);

    expect(entries).toHaveLength(3);
    expect(entries[1]).toMatchObject({
      kind: "tool_group",
      toolIndex: 1,
      state: "completed",
      call: { callId: "call_1" },
    });
    if (entries[1]?.kind === "tool_group") {
      expect(entries[1].results).toHaveLength(1);
      expect(entries[1].results[0]?.callId).toBe("call_1");
    }
  });

  test("keeps tool_call without result as pending", () => {
    const entries = groupChatTraceEntries([toolCall("call_2", "Get-ChildItem -Force")]);
    expect(entries[0]).toMatchObject({
      kind: "tool_group",
      state: "pending",
      toolIndex: 1,
    });
  });

  test("keeps orphan tool_result visible when matching call is missing", () => {
    const entries = groupChatTraceEntries([toolResult("call_3", "Exit code: 1\nOutput:\nboom")]);
    expect(entries[0]).toMatchObject({
      kind: "tool_group",
      state: "orphan_result",
      toolIndex: 0,
      call: null,
    });
  });
});

describe("parseToolResultStatus", () => {
  test("marks exit code 0 as success", () => {
    expect(parseToolResultStatus("Exit code: 0\nWall time: 1.3 seconds\nOutput:\nok")).toMatchObject({
      exitCode: 0,
      tone: "success",
      wallTime: "1.3 seconds",
    });
  });

  test("marks non-zero exit code as error", () => {
    expect(parseToolResultStatus("Exit code: 1\nOutput:\nfail")).toMatchObject({
      exitCode: 1,
      tone: "error",
    });
  });

  test("finds exit code when not at the start of the text", () => {
    expect(parseToolResultStatus("Output:\npartial log\nExit code: 23\nmore text")).toMatchObject({
      exitCode: 23,
      tone: "error",
    });
  });

  test("finds exit code inside json payload", () => {
    expect(
      parseToolResultStatus('{"output":"Success","metadata":{"exit_code":0,"duration_seconds":0.1}}'),
    ).toMatchObject({
      exitCode: 0,
      tone: "success",
    });
  });
});
