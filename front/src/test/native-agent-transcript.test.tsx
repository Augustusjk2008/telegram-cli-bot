import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
});
