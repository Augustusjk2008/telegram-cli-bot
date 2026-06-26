import { expect, test } from "vitest";
import type { ChatTraceEvent } from "../services/types";
import type { AgUiRunState } from "../utils/agUiRunReducer";
import { buildNativeAgentTranscriptEntries } from "../utils/nativeAgentTranscript";

test("keeps native transcript events in real order around commentary", () => {
  const trace: ChatTraceEvent[] = [
    { kind: "tool_call", summary: "bash", callId: "call-1", toolName: "bash" },
    { kind: "tool_result", summary: "Exit code: 0", callId: "call-1" },
    {
      kind: "commentary",
      rawType: "message.text.reclassified",
      summary: "先按仓库源码文件做一次统计，给你总行数和一个按语言的大致拆分。",
    },
  ];

  const agUiState = {
    entries: trace.map((item, index) => ({
      id: `entry-${index}`,
      seq: index + 1,
      kind: item.kind === "tool_call" ? "tool" : item.kind === "tool_result" ? "event" : "process",
      label: item.kind === "tool_call" ? "bash" : item.kind === "tool_result" ? "工具结果" : "过程",
      summary: item.summary,
      collapsedByDefault: item.kind !== "commentary",
      trace: item,
    })),
  } as AgUiRunState;

  const entries = buildNativeAgentTranscriptEntries({ trace, agUiState });

  expect(entries.map((entry) => entry.summary)).toEqual([
    "bash",
    "Exit code: 0",
    "先按仓库源码文件做一次统计，给你总行数和一个按语言的大致拆分。",
  ]);
});

test("uses live entry trace when message trace is not available", () => {
  const trace: ChatTraceEvent[] = [
    { kind: "tool_call", summary: "bash", callId: "call-1", toolName: "bash" },
    {
      kind: "commentary",
      rawType: "message.text.reclassified",
      summary: "准备统计。",
    },
  ];
  const agUiState = {
    entries: trace.map((item, index) => ({
      id: `entry-${index}`,
      seq: index + 1,
      kind: item.kind === "tool_call" ? "tool" : "process",
      label: item.kind === "tool_call" ? "bash" : "过程",
      summary: item.summary,
      collapsedByDefault: item.kind !== "commentary",
      trace: item,
    })),
  } as AgUiRunState;

  const entries = buildNativeAgentTranscriptEntries({ agUiState });

  expect(entries.map((entry) => entry.summary)).toEqual(["bash", "准备统计。"]);
});

test("sorts pi trace entries by sequence and ordinal", () => {
  const trace: ChatTraceEvent[] = [
    { kind: "permission", sequence: 30, summary: "输入", source: "native_agent", payload: { id: "perm-1", uiKind: "input" } },
    { kind: "status", ordinal: 10, summary: "启动", source: "native_agent", payload: { uiKind: "notify" } },
    { kind: "tool_call", sequence: 20, summary: "shell", callId: "call-1", toolName: "shell", source: "native_agent" },
  ];

  const entries = buildNativeAgentTranscriptEntries({ trace });

  expect(entries.map((entry) => entry.summary)).toEqual(["启动", "shell", "输入"]);
  expect(entries[2]).toEqual(expect.objectContaining({
    kind: "permission",
    permission: expect.objectContaining({ uiKind: "input" }),
  }));
});

test("keeps cli trace entries in incoming order", () => {
  const trace: ChatTraceEvent[] = [
    { kind: "permission", sequence: 30, summary: "输入", source: "codex", payload: { id: "perm-1", uiKind: "input" } },
    { kind: "status", ordinal: 10, summary: "启动", source: "codex" },
    { kind: "tool_call", sequence: 20, summary: "shell", callId: "call-1", toolName: "shell", source: "codex" },
  ];

  const entries = buildNativeAgentTranscriptEntries({ trace, mode: "cli" });

  expect(entries.map((entry) => entry.summary)).toEqual(["输入", "启动", "shell"]);
});
