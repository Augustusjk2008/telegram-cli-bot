import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import type { NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";

function processEntries(count: number): NativeAgentTranscriptEntry[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `process-${index}`,
    seq: index,
    kind: "process",
    label: "过程",
    summary: `trace-${index}`,
    collapsedByDefault: false,
    trace: {
      id: `trace-${index}`,
      sequence: index,
      kind: "commentary",
      summary: `trace-${index}`,
    },
  }));
}

function groupedToolEntries(count: number): NativeAgentTranscriptEntry[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `tool-${index}`,
    seq: index,
    kind: "tool",
    label: "shell_command",
    summary: `command-${index}`,
    body: `output-${index}`,
    collapsedByDefault: true,
    trace: {
      id: `tool-trace-${index}`,
      sequence: index,
      kind: "tool_call",
      summary: `command-${index}`,
      callId: `call-${index}`,
    },
  }));
}

describe("transcript and trace virtualization", () => {
  it("defers 1000 process events until expansion and then virtualizes them", async () => {
    render(
      <NativeAgentTranscript
        entries={processEntries(1_000)}
        resultText=""
        state="streaming"
      />,
    );

    expect(screen.queryByTestId("virtualized-native-agent-transcript")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开过程详情" }));

    const list = await screen.findByTestId("virtualized-native-agent-transcript");
    expect(list.querySelectorAll("[data-transcript-entry-id]").length).toBeLessThanOrEqual(10);
  });

  it("defers a large collapsed tool group and virtualizes it when expanded", async () => {
    render(
      <NativeAgentTranscript
        entries={groupedToolEntries(1_000)}
        resultText=""
        state="done"
      />,
    );

    expect(screen.queryByTestId("native-agent-event-group")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开过程详情" }));

    const group = await screen.findByTestId("native-agent-event-group");
    expect(group.querySelectorAll("details").length).toBe(0);

    fireEvent.click(group.querySelector("summary") as HTMLElement);

    const list = await screen.findByTestId("virtualized-native-agent-group");
    expect(list.querySelectorAll("details").length).toBeLessThanOrEqual(20);
  });

  it("does not mount a small collapsed tool group until it is expanded", async () => {
    render(
      <NativeAgentTranscript
        entries={groupedToolEntries(2)}
        resultText=""
        state="done"
      />,
    );

    expect(screen.queryByTestId("native-agent-event-group")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开过程详情" }));

    const group = await screen.findByTestId("native-agent-event-group");
    expect(group.querySelectorAll("details").length).toBe(0);

    fireEvent.click(group.querySelector("summary") as HTMLElement);

    await waitFor(() => expect(group.querySelectorAll("details").length).toBe(2));
  });
});
