import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";
import { DynamicVirtualList } from "../components/virtual/DynamicVirtualList";
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
});
