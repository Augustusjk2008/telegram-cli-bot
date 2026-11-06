import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import type { NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";

function processEntry(
  id: string,
  summary: string,
  seq: number,
  traceKind: "commentary" | "reasoning" | "status" = "commentary",
): NativeAgentTranscriptEntry {
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
      source: "native_agent",
    },
  };
}

function toolEntry(
  id: string,
  kind: "tool_call" | "tool_result",
  summary: string,
  seq: number,
): NativeAgentTranscriptEntry {
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
      source: "native",
      rawType: `deepseek_${kind}`,
      callId: "call-" + id,
      payload: { output: summary },
    },
  };
}

describe("NativeAgentTranscript", () => {
  it("keeps live details collapsed through updates until manually expanded", () => {
    const firstEntry = processEntry("first", "先检查目录", 1);
    const secondEntry = processEntry("second", "再读取文件", 2);
    const { rerender } = render(
      <NativeAgentTranscript
        entries={[firstEntry]}
        resultText=""
        state="streaming"
        mode="native"
        traceCount={1}
        processCount={1}
        traceLoaded
      />,
    );

    const transcript = screen.getByTestId("native-agent-transcript");
    expect(within(transcript).getByRole("button", { name: "展开过程详情" })).toHaveAttribute("aria-expanded", "false");
    expect(within(transcript).queryByText("先检查目录")).not.toBeInTheDocument();

    rerender(
      <NativeAgentTranscript
        entries={[firstEntry, secondEntry]}
        resultText=""
        state="streaming"
        mode="native"
        traceCount={2}
        processCount={2}
        traceLoaded
      />,
    );

    expect(within(transcript).queryByText("再读取文件")).not.toBeInTheDocument();
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    expect(within(transcript).getByText("先检查目录")).toBeInTheDocument();
    expect(within(transcript).getByText("再读取文件")).toBeInTheDocument();
  });

  it("keeps expanded live details mounted while a newer trace tail loads", () => {
    const firstEntry = processEntry("first", "先检查目录", 1);
    const secondEntry = processEntry("second", "再读取文件", 2);
    const onLoadTrace = vi.fn();
    const { rerender } = render(
      <NativeAgentTranscript
        entries={[firstEntry]}
        resultText=""
        state="streaming"
        mode="native"
        traceCount={1}
        processCount={1}
        traceLoaded
        onLoadTrace={onLoadTrace}
      />,
    );

    const transcript = screen.getByTestId("native-agent-transcript");
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    const firstRow = transcript.querySelector('[data-transcript-entry-id="first"]');

    rerender(
      <NativeAgentTranscript
        entries={[firstEntry]}
        resultText=""
        state="streaming"
        mode="native"
        traceCount={2}
        processCount={2}
        traceLoaded={false}
        onLoadTrace={onLoadTrace}
      />,
    );

    expect(within(transcript).getByRole("button", { name: "收起过程详情" })).toHaveAttribute("aria-expanded", "true");
    expect(transcript.querySelector('[data-transcript-entry-id="first"]')).toBe(firstRow);
    expect(onLoadTrace).toHaveBeenCalledTimes(1);

    rerender(
      <NativeAgentTranscript
        entries={[firstEntry, secondEntry]}
        resultText=""
        state="streaming"
        mode="native"
        traceCount={2}
        processCount={2}
        traceLoaded
        onLoadTrace={onLoadTrace}
      />,
    );

    expect(transcript.querySelector('[data-transcript-entry-id="first"]')).toBe(firstRow);
    expect(within(transcript).getByText("再读取文件")).toBeInTheDocument();
  });

  it("collapses CLI details on mobile while keeping the current progress visible", () => {
    const entry = processEntry("cli-process", "正在检查文件", 1);
    render(
      <NativeAgentTranscript
        entries={[entry]}
        resultText=""
        state="streaming"
        mode="cli"
        traceCount={1}
        processCount={1}
        traceLoaded
        mobileLayout
      />,
    );

    const transcript = screen.getByTestId("native-agent-transcript");
    expect(within(transcript).getByRole("status")).toHaveTextContent("正在检查文件");
    expect(transcript.querySelector('[data-transcript-entry-id="cli-process"]')).not.toBeInTheDocument();
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    expect(transcript.querySelector('[data-transcript-entry-id="cli-process"]')).toBeInTheDocument();
  });

  it("splits DeepSeek tool events at each process boundary", () => {
    render(
      <NativeAgentTranscript
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
        mode="cli"
        traceCount={6}
        processCount={2}
        toolCallCount={2}
        traceLoaded
      />,
    );

    const transcript = screen.getByTestId("native-agent-transcript");
    expect(within(transcript).getAllByTestId("native-agent-event-group")).toHaveLength(2);
    expect(within(transcript).getAllByText("过程 1")).toHaveLength(1);
    expect(within(transcript).getAllByText("过程 2")).toHaveLength(1);
  });

  it("keeps endless errors and Continue records collapsed", () => {
    const entries: NativeAgentTranscriptEntry[] = [
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
      <NativeAgentTranscript
        entries={entries}
        resultText="最终回答"
        state="done"
        mode="cli"
      />,
    );

    const transcript = screen.getByTestId("native-agent-transcript");
    expect(within(transcript).getByRole("button", { name: "展开过程详情" })).toHaveAttribute("aria-expanded", "false");
    expect(within(transcript).queryByText("临时失败")).not.toBeInTheDocument();

    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    const retryGroup = within(transcript).getByTestId("native-agent-retry-group");
    expect(retryGroup.querySelector("summary")).toBeTruthy();
    expect(within(retryGroup).queryByText("临时失败")).not.toBeInTheDocument();
    fireEvent.click(retryGroup.querySelector("summary") as HTMLElement);
    expect(within(transcript).getByText("临时失败")).toBeInTheDocument();
  });

  it("aggregates adjacent endless retries across attempts", () => {
    const entries: NativeAgentTranscriptEntry[] = [
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
      <NativeAgentTranscript
        entries={entries}
        resultText="最终回答"
        state="done"
        mode="cli"
      />,
    );

    const transcript = screen.getByTestId("native-agent-transcript");
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    const retryGroups = within(transcript).getAllByTestId("native-agent-retry-group");
    expect(retryGroups).toHaveLength(1);
    expect(within(retryGroups[0]).getByText("连续重试")).toBeInTheDocument();

    fireEvent.click(retryGroups[0].querySelector("summary") as HTMLElement);
    expect(within(retryGroups[0]).getByText("第一次失败")).toBeInTheDocument();
    expect(within(retryGroups[0]).getByText("第二次失败")).toBeInTheDocument();
  });

  it("counts a duplicate final commentary as one visible process", () => {
    render(
      <NativeAgentTranscript
        entries={[
          processEntry("analysis", "分析完成", 1),
          processEntry("final-duplicate", "最终回答", 2),
        ]}
        resultText="最终回答"
        state="done"
        mode="native"
        traceCount={2}
        processCount={2}
        traceLoaded
      />,
    );

    const transcript = screen.getByTestId("native-agent-transcript");
    expect(within(transcript).getByText("1 条过程")).toBeInTheDocument();
    expect(within(transcript).queryByText("2 条过程")).not.toBeInTheDocument();
  });
});
