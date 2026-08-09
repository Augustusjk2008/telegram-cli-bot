import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import { DynamicVirtualList } from "../components/virtual/DynamicVirtualList";
import type { NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";
import { createChatHistoryFixture } from "./fixtures/performance";

describe("frontend performance invariants", () => {
  it("bounds mounted rows for a 1000-message history", () => {
    const messages = createChatHistoryFixture({ messageCount: 1_000 });
    render(
      <DynamicVirtualList
        items={messages}
        getKey={(item) => item.id}
        renderItem={(item) => <div data-testid="message-row">{item.text}</div>}
        estimateHeight={80}
        overscan={6}
        dataTestId="message-list"
      />,
    );

    expect(screen.getAllByTestId("message-row").length).toBeLessThanOrEqual(20);
  });

  it("renders a 100 KiB completed message without truncating content", () => {
    const content = "x".repeat(100 * 1024);
    const { container } = render(<MarkdownContent content={content} variant="chat" />);

    expect(container.textContent).toHaveLength(content.length);
  });

  it("bounds mounted rows for 5000 expanded trace events", () => {
    const entries: NativeAgentTranscriptEntry[] = Array.from({ length: 5_000 }, (_, index) => ({
      id: `trace-${index}`,
      seq: index,
      kind: "event",
      label: "事件",
      summary: `trace-${index}`,
      collapsedByDefault: false,
      trace: {
        id: `trace-${index}`,
        sequence: index,
        kind: "status",
        source: "codex",
        summary: `trace-${index}`,
      },
    }));
    render(
      <NativeAgentTranscript
        entries={entries}
        resultText=""
        mode="cli"
        traceCount={entries.length}
        processCount={entries.length}
        traceLoaded
      />,
    );

    const list = screen.getByTestId("virtualized-native-agent-transcript");
    expect(list.querySelectorAll("[data-transcript-entry-id]").length).toBeLessThanOrEqual(10);
  });
});
