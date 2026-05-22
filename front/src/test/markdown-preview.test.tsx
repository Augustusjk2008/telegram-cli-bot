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
  vi.restoreAllMocks();
});

function mockClipboardWrite() {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

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
  expect(screen.queryByRole("button", { name: "复制代码块" })).not.toBeInTheDocument();
});

test("keeps rendered mermaid diagram stable when parent rerenders with same content", async () => {
  const content = [
    "```mermaid",
    "graph TD",
    "A-->C",
    "```",
  ].join("\n");
  const { rerender } = render(<MarkdownPreview content={content} />);

  await waitFor(() => {
    expect(mermaidRenderMock).toHaveBeenCalledTimes(1);
  });
  expect(screen.queryByText("正在渲染 Mermaid 图表...")).not.toBeInTheDocument();

  rerender(<MarkdownPreview content={content} />);

  expect(screen.queryByText("正在渲染 Mermaid 图表...")).not.toBeInTheDocument();
  await waitFor(() => {
    expect(mermaidRenderMock).toHaveBeenCalledTimes(1);
  });
});

test("copies fenced code blocks", async () => {
  const user = userEvent.setup();
  const writeText = mockClipboardWrite();

  render(
    <MarkdownPreview
      content={[
        "```powershell",
        "python -m pytest tests -q",
        "```",
      ].join("\n")}
    />,
  );

  await user.click(screen.getByRole("button", { name: "复制代码块" }));

  expect(writeText).toHaveBeenCalledWith("python -m pytest tests -q");
  expect(screen.getByRole("button", { name: "已复制代码块" })).toBeDisabled();
});

test("does not add copy buttons to inline code", () => {
  render(<MarkdownPreview content={"运行 `python -m bot` 启动。"} />);

  expect(screen.queryByRole("button", { name: "复制代码块" })).not.toBeInTheDocument();
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
