import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it,  } from "vitest";
import { CliTranscript } from "../components/CliTranscript";
import type { CliTranscriptEntry } from "../utils/cliTranscript";

function processEntry(
  id: string,
  summary: string,
  seq: number,
  traceKind: "commentary" | "reasoning" | "status" = "commentary",
): CliTranscriptEntry {
  return {
    id,
    seq,
    kind: "process",
    label: "过程",
    summary,
    collapsedByDefault: false,
    trace: {
      id: "trace-" + id,
      sequence: seq,
      kind: traceKind,
      summary,
      source: "codex",
    },
  };
}

function toolEntry(
  id: string,
  kind: "tool_call" | "tool_result",
  summary: string,
  seq: number,
): CliTranscriptEntry {
  const isCall = kind === "tool_call";
  return {
    id,
    seq,
    kind: isCall ? "tool" : "event",
    label: isCall ? "read" : "工具结果",
    summary,
    body: summary,
    collapsedByDefault: true,
    trace: {
      id: `trace-${id}`,
      sequence: seq,
      kind,
      summary,
      source: "deepseek",
      rawType: `deepseek_${kind}`,
      callId: "call-" + id,
      payload: { output: summary },
    },
  };
}

describe("CliTranscript", () => {

  it("collapses CLI details on mobile while keeping the current progress visible", () => {
    const entry = processEntry("cli-process", "正在检查文件", 1);
    render(
      <CliTranscript
        entries={[entry]}
        resultText=""
        state="streaming"

        traceCount={1}
        processCount={1}
        traceLoaded
        mobileLayout
      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    expect(within(transcript).getByRole("status")).toHaveTextContent("正在检查文件");
    expect(transcript.querySelector('[data-transcript-entry-id="cli-process"]')).not.toBeInTheDocument();
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    expect(transcript.querySelector('[data-transcript-entry-id="cli-process"]')).toBeInTheDocument();
  });

  it("splits DeepSeek tool events at each process boundary", () => {
    render(
      <CliTranscript
        entries={[
          processEntry("step-1", "开始步骤 1", 1, "status"),
          toolEntry("call-1", "tool_call", "读取文件 A", 2),
          toolEntry("result-1", "tool_result", "文件 A 已读取", 3),
          processEntry("step-2", "先分析文件 B", 4, "reasoning"),
          toolEntry("call-2", "tool_call", "读取文件 B", 5),
          toolEntry("result-2", "tool_result", "文件 B 已读取", 6),
        ]}
        resultText=""
        state="streaming"

        traceCount={6}
        processCount={2}
        toolCallCount={2}
        traceLoaded
      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    expect(within(transcript).getAllByTestId("cli-event-group")).toHaveLength(2);
    expect(within(transcript).getAllByText("过程 1")).toHaveLength(1);
    expect(within(transcript).getAllByText("过程 2")).toHaveLength(1);
  });

  it("keeps endless errors and Continue records collapsed", () => {
    const entries: CliTranscriptEntry[] = [
      {
        id: "endless-error-1",
        seq: 1,
        kind: "endless_error",
        label: "错误",
        summary: "临时失败",
        collapsedByDefault: true,
      },
      {
        id: "endless-continue-1",
        seq: 2,
        kind: "endless_continue",
        label: "Continue",
        summary: "Continue",
        collapsedByDefault: true,
      },
    ];

    render(
      <CliTranscript
        entries={entries}
        resultText="最终回答"
        state="done"

      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    expect(within(transcript).getByRole("button", { name: "展开过程详情" })).toHaveAttribute("aria-expanded", "false");
    expect(within(transcript).queryByText("临时失败")).not.toBeInTheDocument();

    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    const retryGroup = within(transcript).getByTestId("cli-retry-group");
    expect(retryGroup.querySelector("summary")).toBeTruthy();
    expect(within(retryGroup).queryByText("临时失败")).not.toBeInTheDocument();
    fireEvent.click(retryGroup.querySelector("summary") as HTMLElement);
    expect(within(transcript).getByText("临时失败")).toBeInTheDocument();
  });

  it("aggregates adjacent endless retries across attempts", () => {
    const entries: CliTranscriptEntry[] = [
      {
        id: "endless-error-1",
        seq: 1,
        kind: "endless_error",
        label: "错误",
        summary: "第一次失败",
        attempt: 1,
        collapsedByDefault: true,
      },
      {
        id: "endless-continue-1",
        seq: 2,
        kind: "endless_continue",
        label: "Continue",
        summary: "Continue 1",
        attempt: 1,
        collapsedByDefault: true,
      },
      {
        id: "endless-error-2",
        seq: 3,
        kind: "endless_error",
        label: "错误",
        summary: "第二次失败",
        attempt: 2,
        collapsedByDefault: true,
      },
      {
        id: "endless-continue-2",
        seq: 4,
        kind: "endless_continue",
        label: "Continue",
        summary: "Continue 2",
        attempt: 2,
        collapsedByDefault: true,
      },
    ];

    render(
      <CliTranscript
        entries={entries}
        resultText="最终回答"
        state="done"

      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    const retryGroups = within(transcript).getAllByTestId("cli-retry-group");
    expect(retryGroups).toHaveLength(1);
    expect(within(retryGroups[0]).getByText("连续重试")).toBeInTheDocument();

    fireEvent.click(retryGroups[0].querySelector("summary") as HTMLElement);
    expect(within(retryGroups[0]).getByText("第一次失败")).toBeInTheDocument();
    expect(within(retryGroups[0]).getByText("第二次失败")).toBeInTheDocument();
  });

});
