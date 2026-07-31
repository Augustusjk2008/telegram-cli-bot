import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import type { NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";

function processEntry(id: string, summary: string, seq: number): NativeAgentTranscriptEntry {
  return {
    id,
    seq,
    kind: "process",
    label: "过程",
    summary,
    collapsedByDefault: false,
    trace: {
      id: `trace-${id}`,
      sequence: seq,
      kind: "commentary",
      summary,
      source: "native_agent",
    },
  };
}

describe("NativeAgentTranscript process details", () => {
  it("keeps live AG-UI details collapsed through updates until manually expanded", () => {
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

    expect(within(transcript).queryByText("先检查目录")).not.toBeInTheDocument();
    expect(within(transcript).queryByText("再读取文件")).not.toBeInTheDocument();

    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));

    expect(within(transcript).getByRole("button", { name: "收起过程详情" })).toHaveAttribute("aria-expanded", "true");
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
    expect(firstRow).not.toBeNull();

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
        entries={[firstEntry]}
        resultText=""
        state="streaming"
        mode="native"
        traceCount={2}
        processCount={2}
        traceLoaded={false}
        isTraceLoading
        onLoadTrace={onLoadTrace}
      />,
    );

    expect(within(transcript).getByText("正在加载过程详情...")).toBeInTheDocument();
    expect(transcript.querySelector('[data-transcript-entry-id="first"]')).toBe(firstRow);

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

    expect(within(transcript).queryByText("正在加载过程详情...")).not.toBeInTheDocument();
    expect(transcript.querySelector('[data-transcript-entry-id="first"]')).toBe(firstRow);
    expect(within(transcript).getByText("再读取文件")).toBeInTheDocument();
  });

  it("requests each newer missing trace target while details stay expanded", () => {
    const firstEntry = processEntry("first", "先检查目录", 1);
    const onLoadTrace = vi.fn();
    const { rerender } = render(
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

    const transcript = screen.getByTestId("native-agent-transcript");
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    expect(onLoadTrace).toHaveBeenCalledTimes(1);

    rerender(
      <NativeAgentTranscript
        entries={[firstEntry]}
        resultText=""
        state="streaming"
        mode="native"
        traceCount={3}
        processCount={3}
        traceLoaded={false}
        onLoadTrace={onLoadTrace}
      />,
    );

    expect(within(transcript).getByRole("button", { name: "收起过程详情" })).toHaveAttribute("aria-expanded", "true");
    expect(onLoadTrace).toHaveBeenCalledTimes(2);
  });
});
