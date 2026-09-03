import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";
import { normalizeLatexMathDelimiters } from "../markdown/latexDelimiters";
import { normalizeLatexMath } from "../markdown/normalizeLatexMath";

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

  it("normalizes LaTeX delimiters in preview content as well", () => {
    const { container } = render(
      <MarkdownContent content={"预览 \\(x=1\\)。"} variant="preview" />,
    );

    expect(container.querySelector(".katex")).not.toBeNull();
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

  it("continues rendering Markdown dollar-delimited inline and display math", () => {
    const { container } = render(
      <MarkdownContent
        content={["Inline $E = mc^2$.", "", "$$", "\\int_0^1 x^2\\,dx", "$$"].join("\n")}
      />,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(2);
    expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
  });

  it.each(["preview", "desktop-preview"] as const)(
    "renders standard LaTeX delimiters in the %s variant",
    (variant) => {
      const { container } = render(
        <MarkdownContent
          content={String.raw`Inline \(E = mc^2\).

\[
\int_0^1 x^2\,dx
\]`}
          variant={variant}
        />,
      );

      expect(container.querySelectorAll(".katex")).toHaveLength(2);
      expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
      const previewRoot = container.firstElementChild;
      expect(previewRoot?.className).toContain("[&_.katex-display]:max-w-full");
      expect(previewRoot?.className).toContain("[&_.katex-display]:overflow-x-auto");
      expect(previewRoot?.className).toContain("[&_.katex-display]:overflow-y-hidden");
    },
  );

  it("keeps code, raw HTML, links, and existing math byte-for-byte intact", () => {
    const source = [
      String.raw`Outside \(x + 1\).`,
      "",
      "Inline code: `\\(code\\)`.",
      "",
      "~~~latex",
      String.raw`\[`,
      "fenced code",
      String.raw`\]`,
      "~~~",
      "",
      String.raw`    \(indented code\)`,
      "",
      "<div>",
      String.raw`\(raw HTML\)`,
      "</div>",
      "",
      String.raw`[docs](https://example.test/\(target\) "\(title\)")`,
      "",
      String.raw`https://example.test/\(bare-target\)`,
      "",
      String.raw`Existing $\text{\(already math\)}$.`,
    ].join("\n");
    const expected = source.replace(String.raw`Outside \(x + 1\).`, "Outside $x + 1$.");

    expect(normalizeLatexMath(source)).toBe(expected);
  });

  it("keeps matched inline HTML elements and their bodies unchanged", () => {
    const source = [
      String.raw`Before \(outside\).`,
      "",
      String.raw`<span data-value="\(attribute\)"><em>\(raw body\)</em></span>`,
      "",
      String.raw`After \(outside too\).`,
    ].join("\n");

    expect(normalizeLatexMath(source)).toBe([
      "Before $outside$.",
      "",
      String.raw`<span data-value="\(attribute\)"><em>\(raw body\)</em></span>`,
      "",
      "After $outside too$.",
    ].join("\n"));
  });

  it("keeps raw HTML element bodies unchanged across Markdown blocks", () => {
    const source = [
      "<details>",
      "<summary>Title</summary>",
      "",
      String.raw`\(inside details\)`,
      "",
      "</details>",
      "",
      "<span>",
      "",
      String.raw`\(inside span\)`,
      "",
      "</span>",
      "",
      String.raw`Outside \(math\).`,
    ].join("\n");

    expect(normalizeLatexMath(source)).toBe(
      source.replace(String.raw`Outside \(math\).`, "Outside $math$."),
    );
  });

  it("does not treat tags inside CDATA or processing instructions as HTML containers", () => {
    const source = [
      "<![CDATA[",
      ">",
      "<fake>",
      "]]>",
      "",
      "<?target",
      ">",
      "<fake>",
      "?>",
      "",
      String.raw`Outside \(math\).`,
    ].join("\n");

    expect(normalizeLatexMath(source)).toBe(
      source.replace(String.raw`Outside \(math\).`, "Outside $math$."),
    );
  });

  it("normalizes explicit link labels without changing link destinations", () => {
    const source = String.raw`[\(label math\)](https://example.test/\(target\) "\(title\)")`;

    expect(normalizeLatexMath(source)).toBe(
      String.raw`[$label math$](https://example.test/\(target\) "\(title\)")`,
    );
  });

  it("normalizes standalone display delimiters and preserves line endings", () => {
    expect(normalizeLatexMath(String.raw`\[ E = mc^2 \]`)).toBe("$$\n E = mc^2 \n$$");
    expect(normalizeLatexMath("\\[\r\nE = mc^2\r\n\\]")).toBe("$$\r\nE = mc^2\r\n$$");
    expect(normalizeLatexMath("head\r\n\r\n\\[ E = mc^2 \\]\nlast")).toBe(
      "head\r\n\r\n$$\n E = mc^2 \n$$\nlast",
    );
    expect(normalizeLatexMath("\\[ E = mc^2 \\]\rnext")).toBe("$$\r E = mc^2 \r$$\rnext");
    expect(normalizeLatexMath(String.raw`Prefix \[E = mc^2\] suffix`)).toBe(
      String.raw`Prefix \[E = mc^2\] suffix`,
    );
  });

  it("pairs across Markdown emphasis without crossing protected regions", () => {
    const source = [
      String.raw`Unicode 🙂 \(a **b** c\).`,
      "",
      "Broken \\(before `code` after\\).",
    ].join("\n");

    expect(normalizeLatexMath(source)).toBe([
      "Unicode 🙂 $a **b** c$.",
      "",
      "Broken \\(before `code` after\\).",
    ].join("\n"));
  });

  it("leaves escaped, unmatched, currency, and dollar-containing formulas unchanged", () => {
    const source = [
      String.raw`Orphan close \).`,
      String.raw`Escaped \\(literal\\).`,
      "Price is $5.00.",
      String.raw`Price formula \(\text{cost: \$5}\).`,
      String.raw`Unclosed \(x + 1`,
    ].join("\n");

    expect(normalizeLatexMath(source)).toBe(source);
    expect(normalizeLatexMath(String.raw`Broken \(outer; valid \(x\).`)).toBe(
      String.raw`Broken \(outer; valid $x$.`,
    );
  });

  it("handles many unmatched delimiters without consuming later content", () => {
    const unmatched = Array.from({ length: 5_000 }, () => String.raw`\(`).join(" ");
    expect(normalizeLatexMath(unmatched)).toBe(unmatched);
  });

  it("keeps unsupported KaTeX commands visible without crashing the preview", () => {
    const { container } = render(
      <MarkdownContent content={String.raw`Unsupported \(\begin{notreal}x\end{notreal}\).`} />,
    );

    const error = container.querySelector(".katex-error");
    expect(error).not.toBeNull();
    expect(error).toHaveTextContent(String.raw`\begin{notreal}x\end{notreal}`);
  });
});
