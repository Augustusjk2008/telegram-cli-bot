import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";

describe("frontend performance invariants", () => {
  it("renders a 100 KiB completed message without truncating content", () => {
    const content = "x".repeat(100 * 1024);
    const { container } = render(<MarkdownContent content={content} variant="chat" />);

    expect(container.textContent).toHaveLength(content.length);
  });
});
