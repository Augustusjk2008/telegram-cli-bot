import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { MarkdownPreview } from "../components/MarkdownPreview";

const mermaidInitializeMock = vi.fn();
const mermaidRenderMock = vi.fn(async (id: string, code: string) => ({
  svg: `<svg data-render-id="${id}" viewBox="0 0 120 80"><text>${code}</text></svg>`,
  bindFunctions: undefined,
}));

vi.mock("mermaid", () => ({
  default: {
    initialize: mermaidInitializeMock,
    render: mermaidRenderMock,
  },
}));

afterEach(() => {
  mermaidInitializeMock.mockClear();
  mermaidRenderMock.mockClear();
});

test("renders latex formulas with katex markup", () => {
  const { container } = render(
    <MarkdownPreview content={"行内公式 $E=mc^2$。\n\n$$\n\\int_0^1 x^2 dx\n$$"} />,
  );

  expect(container.querySelector(".katex")).not.toBeNull();
  expect(container.querySelector(".katex-display")).not.toBeNull();
});

test("renders mermaid code fences as svg diagrams", async () => {
  const { container } = render(
    <MarkdownPreview
      content={[
        "# Mermaid Demo",
        "",
        "```mermaid",
        "graph TD",
        "A-->B",
        "```",
      ].join("\n")}
    />,
  );

  await waitFor(() => {
    expect(mermaidRenderMock).toHaveBeenCalledTimes(1);
  });

  expect(mermaidInitializeMock).toHaveBeenCalledTimes(1);
  expect(mermaidRenderMock).toHaveBeenCalledWith(expect.stringMatching(/^mermaid-/), "graph TD\nA-->B");
  expect(container.querySelector("[data-mermaid-diagram='true']")?.innerHTML).toContain("<svg");
});

test("routes local file links through onFileLinkClick", async () => {
  const user = userEvent.setup();
  const onFileLinkClick = vi.fn();

  render(
    <MarkdownPreview
      content="[查看 README](C:/workspace/README.md)"
      onFileLinkClick={onFileLinkClick}
    />,
  );

  await user.click(screen.getByRole("link", { name: "查看 README" }));

  expect(onFileLinkClick).toHaveBeenCalledWith("C:/workspace/README.md");
});

test("routes same-origin absolute file urls through onFileLinkClick", async () => {
  const user = userEvent.setup();
  const onFileLinkClick = vi.fn();

  render(
    <MarkdownPreview
      content="[查看文档](http://127.0.0.1:8765/abs/path/C:/workspace/docs/guide.md:1)"
      onFileLinkClick={onFileLinkClick}
    />,
  );

  await user.click(screen.getByRole("link", { name: "查看文档" }));

  expect(onFileLinkClick).toHaveBeenCalledWith("http://127.0.0.1:8765/abs/path/C:/workspace/docs/guide.md:1");
});

test("routes bare same-origin absolute file urls through onFileLinkClick", async () => {
  const user = userEvent.setup();
  const onFileLinkClick = vi.fn();

  render(
    <MarkdownPreview
      content="http://127.0.0.1:8765/abs/path/C:/workspace/docs/guide.md:1"
      onFileLinkClick={onFileLinkClick}
    />,
  );

  await user.click(screen.getByRole("link", { name: "http://127.0.0.1:8765/abs/path/C:/workspace/docs/guide.md:1" }));

  expect(onFileLinkClick).toHaveBeenCalledWith("http://127.0.0.1:8765/abs/path/C:/workspace/docs/guide.md:1");
});

test("routes abs-path file urls through onFileLinkClick", async () => {
  const user = userEvent.setup();
  const onFileLinkClick = vi.fn();

  render(
    <MarkdownPreview
      content="[查看文档](/abs/path/C:/workspace/docs/guide.md:1)"
      onFileLinkClick={onFileLinkClick}
    />,
  );

  await user.click(screen.getByRole("link", { name: "查看文档" }));

  expect(onFileLinkClick).toHaveBeenCalledWith("/abs/path/C:/workspace/docs/guide.md:1");
});

test("keeps original href on local file links", () => {
  render(
    <MarkdownPreview
      content="[查看 README](/C:/workspace/README.md:12)"
      onFileLinkClick={vi.fn()}
    />,
  );

  expect(screen.getByRole("link", { name: "查看 README" }).getAttribute("href")).toBe("/C:/workspace/README.md:12");
});
