import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";

describe("MarkdownContent", () => {
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
