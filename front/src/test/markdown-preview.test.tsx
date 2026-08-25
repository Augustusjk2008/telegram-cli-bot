import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";
import { normalizeLatexMathDelimiters } from "../markdown/latexDelimiters";

const GLOBAL_STYLES = readFileSync("src/styles/global.css", "utf8");

describe("MarkdownContent", () => {
  it("renders embedded README HTML in file previews", () => {
    const resolveImageSrc = vi.fn((src: string) => `/resolved/${src}`);
    const { container } = render(
      <MarkdownContent
        content={[
          '<p align="center">',
          '  <img src="front/public/assets/app-logo.svg" width="112" alt="Orbit Safe Claw Logo">',
          "</p>",
          '<h1 align="center">Orbit Safe Claw</h1>',
          "<details>",
          "<summary><strong>从源码安装</strong></summary>",
          "安装说明",
          "</details>",
        ].join("\n")}
        variant="preview"
        resolveImageSrc={resolveImageSrc}
      />,
    );

    expect(container.querySelector("p")).toHaveStyle({ textAlign: "center" });
    expect(screen.getByRole("heading", { level: 1 })).toHaveStyle({ textAlign: "center" });
    expect(screen.getByRole("img", { name: "Orbit Safe Claw Logo" })).toHaveAttribute("width", "112");
    expect(screen.getByRole("img", { name: "Orbit Safe Claw Logo" })).toHaveAttribute(
      "src",
      "/resolved/front/public/assets/app-logo.svg",
    );
    expect(container.querySelector("details summary")).toHaveTextContent("从源码安装");
  });

  it("sanitizes dangerous embedded HTML in file previews", () => {
    const { container } = render(
      <MarkdownContent
        content={'<img src="https://example.com/logo.png" alt="logo" onerror="alert(1)"><script>alert(2)</script>'}
        variant="preview"
      />,
    );

    expect(screen.getByRole("img", { name: "logo" })).not.toHaveAttribute("onerror");
    expect(container.querySelector("script")).toBeNull();
    expect(container).not.toHaveTextContent("alert(2)");
  });

  it("keeps embedded HTML disabled in chat messages", () => {
    const { container } = render(
      <MarkdownContent content={"消息中的 <strong>HTML</strong>"} variant="chat" />,
    );

    expect(container.querySelector("strong")).toBeNull();
    expect(container).toHaveTextContent("<strong>HTML</strong>");
  });

  it("renders parenthesized and bracketed LaTeX delimiters", () => {
    const { container } = render(
      <MarkdownContent
        content={[
          "\\[",
          "[x]_+=\\max(0,x)",
          "\\]",
          "",
          "全国是图 \\(G=(V,E)\\)，价格为 $p=1$。",
        ].join("\n")}
        variant="chat"
      />,
    );

    expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
    expect(container.querySelectorAll(".katex")).toHaveLength(3);
    expect(Array.from(container.querySelectorAll("annotation")).map((node) => node.textContent)).toEqual([
      "[x]_+=\\max(0,x)",
      "G=(V,E)",
      "p=1",
    ]);
  });

  it("does not treat LaTeX delimiters in Markdown code as formulas", () => {
    const { container } = render(
      <MarkdownContent
        content={[
          "外部公式 \\(x=1\\)。",
          "",
          "行内代码 `\\(not_math\\)`。",
          "",
          "```tex",
          "\\[",
          "not_math",
          "\\]",
          "```",
        ].join("\n")}
        variant="chat"
      />,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(1);
    expect(Array.from(container.querySelectorAll("code")).map((node) => node.textContent)).toEqual([
      "\\(not_math\\)",
      "\\[\nnot_math\n\\]",
    ]);
  });

  it("leaves escaped and unmatched LaTeX delimiters as text", () => {
    const { container } = render(
      <MarkdownContent
        content={"字面量 \\\\(not_math\\\\)，未闭合 \\(still_text。"}
        variant="chat"
      />,
    );

    expect(container.querySelector(".katex")).toBeNull();
    expect(container).toHaveTextContent("\\(not_math\\)");
    expect(container).toHaveTextContent("(still_text");
  });

  it("normalizes only unambiguous LaTeX delimiter pairs", () => {
    expect(normalizeLatexMathDelimiters("$a \\(b\\) c$ and \\(x\\)")).toBe(
      "$a \\(b\\) c$ and $$x$$",
    );
    expect(normalizeLatexMathDelimiters("\\[x\\]")).toBe("\\[x\\]");
    expect(normalizeLatexMathDelimiters("\\[\nx\n\\]")).toBe("$$\nx\n$$");
    expect(normalizeLatexMathDelimiters("`prefix` \\[\nx\n\\]")).toBe("`prefix` \\[\nx\n\\]");
    expect(normalizeLatexMathDelimiters("$p$ \\[\nx\n\\]")).toBe("$p$ \\[\nx\n\\]");
    expect(normalizeLatexMathDelimiters("$a `tick` \\(b\\) c$ and \\(x\\)")).toBe(
      "$a `tick` \\(b\\) c$ and $$x$$",
    );
    expect(normalizeLatexMathDelimiters("价格是 $5，公式 \\(x=1\\)。")).toBe(
      "价格是 $5，公式 $$x=1$$。",
    );
  });

  it("preserves LaTeX delimiters in nested fenced code", () => {
    const markdown = [
      "> ~~~tex",
      "> \\(not_math\\)",
      "> ~~~",
      "",
      "外部 \\(x=1\\)。",
    ].join("\n");

    expect(normalizeLatexMathDelimiters(markdown)).toBe([
      "> ~~~tex",
      "> \\(not_math\\)",
      "> ~~~",
      "",
      "外部 $$x=1$$。",
    ].join("\n"));

    const fencedMarkdown = [
      "~~~tex",
      "\\(first\\)",
      "- ~~~",
      "\\(second\\)",
      "~~~",
    ].join("\n");
    expect(normalizeLatexMathDelimiters(fencedMarkdown)).toBe(fencedMarkdown);

    const indentedCode = "    \\[\n    not_math\n    \\]";
    expect(normalizeLatexMathDelimiters(indentedCode)).toBe(indentedCode);
    expect(normalizeLatexMathDelimiters("    - \\(not_math\\)")).toBe("    - \\(not_math\\)");
    expect(normalizeLatexMathDelimiters("    > \\(not_math\\)")).toBe("    > \\(not_math\\)");
  });

  it("renders parenthesized LaTeX after an unmatched currency dollar", () => {
    const { container } = render(
      <MarkdownContent content={"价格是 $5，公式 \\(x=1\\)。"} variant="chat" />,
    );

    expect(container.querySelector("annotation")).toHaveTextContent("x=1");
    expect(container).toHaveTextContent("价格是 $5，公式");
  });

  it("handles long escaped delimiter prefixes without quadratic slowdown", () => {
    const markdown = `${"\\".repeat(20_001)}(`;
    const startedAt = performance.now();

    expect(normalizeLatexMathDelimiters(markdown)).toBe(markdown);
    expect(performance.now() - startedAt).toBeLessThan(500);
  });

  it("limits LaTeX delimiter compatibility to chat content", () => {
    const { container } = render(
      <MarkdownContent content={"预览 \\(x=1\\)。"} variant="preview" />,
    );

    expect(container.querySelector(".katex")).toBeNull();
  });

  it("keeps chat display formulas horizontally scrollable", () => {
    expect(GLOBAL_STYLES).toMatch(
      /\.chat-markdown-content\s+\.katex-display\s*\{[^}]*overflow-x:\s*auto;/s,
    );
    expect(GLOBAL_STYLES).toMatch(
      /\.chat-markdown-content\s+\.katex-display\s*>\s*\.katex\s*\{[^}]*min-width:\s*max-content;/s,
    );
  });

  it("keeps ordered list start values when loose step lists are split by bullet details", () => {
    render(
      <MarkdownContent
        content={[
          "实施步骤",
          "1. 素材预览",
          "- 图片直接预览。",
          "",
          "2. 主题颜色选择器",
          "- 颜色盘负责选色。",
          "",
          "3. 原始页改概览",
          "- 展示项目结构。",
          "",
          "建议落地顺序",
          "1. 素材预览",
          "2. 上传入口重做",
          "3. 网络链接支持",
        ].join("\n")}
        variant="chat"
      />,
    );

    const orderedLists = screen.getAllByRole("list").filter((list) => list.tagName === "OL");

    expect(orderedLists).toHaveLength(4);
    expect(orderedLists[0]).not.toHaveAttribute("start");
    expect(orderedLists[1]).toHaveAttribute("start", "2");
    expect(orderedLists[2]).toHaveAttribute("start", "3");
    expect(orderedLists[3]).not.toHaveAttribute("start");
    expect(orderedLists[3]).toHaveTextContent("素材预览");
    expect(orderedLists[3]).toHaveTextContent("上传入口重做");
    expect(orderedLists[3]).toHaveTextContent("网络链接支持");
  });
});
