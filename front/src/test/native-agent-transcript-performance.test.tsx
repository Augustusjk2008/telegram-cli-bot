import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatTracePanel } from "../components/ChatTracePanel";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import type { ChatTraceEvent } from "../services/types";
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
  it("bounds mounted transcript rows for 1000 process events", () => {
    render(
      <NativeAgentTranscript
        entries={processEntries(1_000)}
        resultText=""
        state="streaming"
      />,
    );

    const list = screen.getByTestId("virtualized-native-agent-transcript");
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

    const group = screen.getByTestId("native-agent-event-group");
    expect(group.querySelectorAll("details").length).toBe(0);

    fireEvent.click(group.querySelector("summary") as HTMLElement);

    const list = await screen.findByTestId("virtualized-native-agent-group");
    expect(list.querySelectorAll("details").length).toBeLessThanOrEqual(20);
  });

  it("bounds mounted trace rows when expanded", () => {
    const trace: ChatTraceEvent[] = Array.from({ length: 1_000 }, (_, index) => ({
      id: `trace-${index}`,
      sequence: index,
      kind: "commentary",
      summary: `trace-${index}`,
    }));

    render(
      <ChatTracePanel
        messageId="assistant-1"
        trace={trace}
        expanded
        onToggleExpanded={() => undefined}
      />,
    );

    const list = screen.getByTestId("virtualized-chat-trace");
    expect(list.querySelectorAll("[data-trace-seq]").length).toBeLessThanOrEqual(10);
  });
});
