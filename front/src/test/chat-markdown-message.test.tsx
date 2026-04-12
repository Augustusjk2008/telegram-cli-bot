import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.doUnmock("../components/MarkdownPreview");
});

test("renders completed assistant replies as markdown content", async () => {
  const { ChatMarkdownMessage } = await import("../components/ChatMarkdownMessage");

  render(<ChatMarkdownMessage content={"# 结果\n- 第一项\n- 第二项"} />);

  expect(screen.getByRole("heading", { name: "结果" })).toBeInTheDocument();
  expect(screen.getByText("第一项")).toBeInTheDocument();
  expect(screen.getByText("第二项")).toBeInTheDocument();
});

test("falls back to raw text when markdown rendering throws", async () => {
  vi.doMock("../components/MarkdownPreview", () => ({
    MarkdownContent: () => {
      throw new Error("boom");
    },
  }));

  const { ChatMarkdownMessage } = await import("../components/ChatMarkdownMessage");
  render(<ChatMarkdownMessage content={"C:\\workspace\\demo\\src\\very\\long\\path\\file.ts"} />);

  expect(screen.getByText(/C:\\workspace\\demo\\src\\very\\long\\path\\file.ts/)).toBeInTheDocument();
  expect(screen.getByTestId("assistant-markdown-fallback")).toBeInTheDocument();
});

test("applies overflow-safe classes for long raw paths", async () => {
  const { ChatMarkdownMessage } = await import("../components/ChatMarkdownMessage");
  render(<ChatMarkdownMessage content={"`C:\\workspace\\demo\\src\\very\\long\\path\\file.ts`"} />);

  expect(screen.getByTestId("assistant-markdown-message")).toHaveClass("min-w-0");
});
