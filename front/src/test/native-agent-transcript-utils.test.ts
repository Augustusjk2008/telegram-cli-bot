import { expect, test } from "vitest";
import type { ChatTraceEvent } from "../services/types";
import type { AgUiRunState } from "../utils/agUiRunReducer";
import { buildNativeAgentTranscriptEntries } from "../utils/nativeAgentTranscript";

test("normalizes live native transcript commentary before tool group", () => {
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
    "先按仓库源码文件做一次统计，给你总行数和一个按语言的大致拆分。",
    "bash",
    "Exit code: 0",
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

  expect(entries.map((entry) => entry.summary)).toEqual(["准备统计。", "bash"]);
});
