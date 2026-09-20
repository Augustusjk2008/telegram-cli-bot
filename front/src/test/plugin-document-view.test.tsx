import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DocumentView } from "../components/plugin-renderers/DocumentView";
import type { DocumentViewPayload } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function renderDocument(payload: Omit<DocumentViewPayload, "path">, client = {} as WebBotClient) {
  return render(<DocumentView botAlias="main" client={client} view={{
    pluginId: "document-test",
    viewId: "preview",
    title: "Preview",
    renderer: "document",
    mode: "snapshot",
    payload: { path: "sample.docx", ...payload },
  }} />);
}

describe("DocumentView formatting", () => {
  it("uses paragraph defaults while honoring explicit text overrides and mixed fonts", () => {
    renderDocument({
      formatting: "document",
      blocks: [{
        type: "heading",
        level: 1,
        format: { textStyle: {
          bold: true, italic: true, underline: true, code: true,
          fontSizePx: 22, color: "#123456",
          fontFamily: "Latin Font", fontFamilyEastAsia: "中文字体",
        } },
        runs: [
          { text: "English中文", code: false },
          { text: "plain", bold: false, italic: false, underline: false, code: false, fontSizePx: 0 },
          { text: "marked", highlightColor: "#ffff00", shadingColor: "#ff0000" },
          { text: "shaded", shadingColor: "#aabbcc" },
          { text: "unhighlighted", highlightColor: "transparent", shadingColor: "#aabbcc" },
        ],
      }],
    });
    const heading = screen.getByRole("heading", { level: 1 });
    const surface = heading.parentElement!;
    expect(surface).toHaveStyle({ backgroundColor: "#ffffff", color: "#000000", lineHeight: "normal" });
    expect(surface).not.toHaveClass("space-y-4");
    expect(heading).toHaveStyle({ fontSize: "22px", color: "#123456" });
    expect(screen.getByText("English")).toHaveStyle({ fontFamily: '"Latin Font", "中文字体"' });
    expect(screen.getByText("中文")).toHaveStyle({ fontFamily: '"中文字体", "Latin Font"' });
    const plain = screen.getByText("plain").parentElement!;
    expect(plain).toHaveStyle({ fontWeight: "normal", fontStyle: "normal", textDecoration: "none", fontSize: "0px" });
    expect(plain.querySelector("strong, em, u, code")).toBeNull();
    expect(screen.getByText("marked").closest("strong")!.parentElement).toHaveStyle({ backgroundColor: "#ffff00" });
    expect(screen.getByText("shaded").closest("strong")!.parentElement).toHaveStyle({ backgroundColor: "#aabbcc" });
    expect(screen.getByText("unhighlighted").closest("strong")!.parentElement).toHaveStyle({ backgroundColor: "#aabbcc" });
  });

  it("quotes font names and renders markup as selectable text", () => {
    const text = "<img src=x onerror=alert(1)>";
    const { container } = renderDocument({
      formatting: "document",
      blocks: [{ type: "paragraph", runs: [{
        text, fontFamily: 'Odd" Font\\Name\n, serif; color: red',
      }] }],
    });
    const run = screen.getByText(text);
    // CSSOM may normalize escape sequences; the complete name stays one value.
    expect(run.style.fontFamily).toMatch(/^".*"$/s);
    expect(run.style.fontFamily).toContain(", serif; color: red");
    expect(Array.from(run.style)).toEqual(["font-family"]);
    expect(run.style.color).toBe("");
    expect(container.querySelector("img")).toBeNull();
    const selection = window.getSelection()!;
    const range = document.createRange();
    range.selectNodeContents(run);
    selection.removeAllRanges();
    selection.addRange(range);
    expect(selection.toString()).toBe(text);
    selection.removeAllRanges();
  });

  it("preserves blank paragraphs, line spacing, zero spacing, and list hanging indents", () => {
    const { container } = renderDocument({
      formatting: "document",
      blocks: [
        { type: "paragraph", runs: [{ text: "aligned\nsecond line" }], format: {
          align: "justify", indentLeftPx: 32, indentRightPx: 12, firstLineIndentPx: 16,
          spaceBeforePx: 8, spaceAfterPx: 0, lineSpacing: { mode: "multiple", value: 1.5 },
        } },
        { type: "paragraph", runs: [], format: {
          textStyle: { fontSizePx: 24 }, lineSpacing: { mode: "exact", value: 30 },
        } },
        { type: "paragraph", runs: [{ text: "zero" }], format: {
          indentLeftPx: 0, firstLineIndentPx: 0, spaceBeforePx: 0,
          lineSpacing: { mode: "exact", value: 0 },
        } },
        { type: "paragraph", runs: [{ text: "large", fontSizePx: 36 }], format: {
          lineSpacing: { mode: "atLeast", value: 20 },
        } },
        { type: "list_item", depth: 5, marker: "2.", markerStyle: { fontFamily: "Symbol", color: "#123456" }, runs: [{ text: "list text" }], format: {
          align: "right", indentLeftPx: 40, firstLineIndentPx: -20,
          spaceBeforePx: 0, spaceAfterPx: 4, lineSpacing: { mode: "multiple", value: 2 },
        } },
      ],
    });
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs[0]).toHaveStyle({
      textAlign: "justify", marginLeft: "32px", marginRight: "12px", textIndent: "16px",
      marginTop: "8px", marginBottom: "0px", lineHeight: "1.5",
    });
    expect(paragraphs[0].textContent).toBe("aligned\nsecond line");
    expect(paragraphs[1]).toHaveStyle({ fontSize: "24px", lineHeight: "30px" });
    expect(paragraphs[1].querySelector("br")).not.toBeNull();
    expect(paragraphs[2]).toHaveStyle({ marginLeft: "0px", textIndent: "0px", marginTop: "0px", lineHeight: "0px" });
    expect(paragraphs[3]).toHaveStyle({ lineHeight: "20px" });
    expect(screen.getByText("large")).toHaveStyle({ fontSize: "36px", lineHeight: "normal" });
    expect(paragraphs[4]).toHaveStyle({
      textAlign: "right", marginLeft: "40px", textIndent: "-20px", marginTop: "0px", marginBottom: "4px", lineHeight: "2",
    });
    expect(screen.getByText("2.").parentElement).toHaveStyle({ minWidth: "20px", textIndent: "0" });
    expect(screen.getByText("2.")).toHaveStyle({ fontFamily: '"Symbol"', color: "#123456" });
    expect(paragraphs[4]).not.toHaveClass("flex", "gap-3");
  });

  it("renders table grids, merged cells, paragraph boundaries, and image artifacts", async () => {
    const client = { getPluginArtifactBlob: vi.fn().mockRejectedValue(new Error("image unavailable")) } as unknown as WebBotClient;
    renderDocument({
      formatting: "document",
      blocks: [{
        type: "table",
        width: { unit: "percent", value: 75 },
        columnWidthsPx: [80, 100, 120],
        shadingColor: "#eeeeee",
        cellPadding: { topPx: 4, rightPx: 5, bottomPx: 6, leftPx: 7 },
        borders: {
          top: { style: "double", widthPx: 3, color: "#000000" },
          bottom: { style: "solid", widthPx: 1, color: "#000000" },
          left: { style: "solid", widthPx: 1, color: "#000000" },
          right: { style: "solid", widthPx: 1, color: "#000000" },
          insideHorizontal: { style: "dotted", widthPx: 1, color: "#222222" },
          insideVertical: { style: "dashed", widthPx: 2, color: "#333333" },
        },
        rows: [
          { cells: [
            { runs: [{ text: "fallback hidden" }], rowSpan: 2, colSpan: 2,
              width: { unit: "px", value: 180 }, shadingColor: "#ffffcc", verticalAlign: "center",
              padding: { topPx: 0, leftPx: 0 }, borders: { top: { style: "none" } },
              paragraphs: [
                { type: "paragraph", runs: [{ text: "first cell paragraph" }], format: { align: "center", spaceAfterPx: 10 } },
                { type: "heading", level: 3, runs: [{ text: "second cell paragraph" }], format: { textStyle: { bold: false, fontSizePx: 18 } } },
              ],
            },
            { runs: [{ text: "top right" }] },
          ] },
          { cells: [{ runs: [], paragraphs: [
            { type: "image", artifactId: "inline-picture", filename: "picture.png", contentType: "image/png" },
          ] }] },
        ],
      }],
    }, client);
    const table = screen.getByRole("table");
    expect(table).toHaveStyle({ width: "75%", backgroundColor: "#eeeeee" });
    expect(Array.from(table.querySelectorAll("col")).map((col) => col.style.width)).toEqual(["80px", "100px", "120px"]);
    const cells = within(table).getAllByRole("cell");
    expect(cells).toHaveLength(3);
    expect(cells[0]).toHaveAttribute("rowspan", "2");
    expect(cells[0]).toHaveAttribute("colspan", "2");
    expect(cells[0]).toHaveStyle({
      width: "180px", backgroundColor: "#ffffcc", verticalAlign: "middle",
      paddingTop: "0px", paddingRight: "5px", paddingBottom: "6px", paddingLeft: "0px",
      borderTopStyle: "none", borderRight: "2px dashed #333333", borderBottom: "1px solid #000000",
    });
    expect(screen.queryByText("fallback hidden")).not.toBeInTheDocument();
    expect(screen.getByText("first cell paragraph").closest("p")).toHaveStyle({ textAlign: "center", marginBottom: "10px" });
    expect(within(cells[0]).getByRole("heading")).toHaveStyle({ fontWeight: "normal", fontSize: "18px" });
    expect(cells[2]).toHaveStyle({ borderLeft: "2px dashed #333333", borderRight: "1px solid #000000", borderTop: "1px dotted #222222" });
    expect(await screen.findByText("image unavailable")).toBeInTheDocument();
    expect(client.getPluginArtifactBlob).toHaveBeenCalledWith("main", "inline-picture");
  });

  it("retains legacy headings, lists, tables, and slide appearance without opt-in", () => {
    renderDocument({
      blocks: [
        { type: "heading", level: 1, runs: [{ text: "legacy heading" }] },
        { type: "paragraph", runs: [{ text: "legacy paragraph", bold: true }] },
        { type: "list_item", depth: 2, runs: [{ text: "legacy list" }] },
        { type: "table", rows: [{ cells: [{ runs: [{ text: "legacy cell" }] }] }] },
        { type: "slide", slideNumber: 1, widthPx: 960, heightPx: 540, items: [{
          type: "text", frame: { x: 12, y: 24, width: 200, height: 50 },
          paragraphs: [{ runs: [{ text: "slide text", fontSizePx: 28 }], align: "center" }],
        }, {
          type: "table", frame: { x: 0, y: 80, width: 200, height: 80 },
          rows: [{ cells: [{ runs: [{ text: "slide cell" }] }] }],
        }] },
      ],
    });
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveClass("text-2xl", "leading-tight", "text-[var(--text)]");
    expect(heading.parentElement).toHaveClass("space-y-4");
    expect(screen.getByText("legacy paragraph").closest("p")).toHaveClass("leading-7");
    expect(screen.getByText("legacy paragraph").tagName).toBe("STRONG");
    expect(screen.getByText("legacy list").parentElement!.parentElement).toHaveStyle({ paddingLeft: "40px" });
    expect(screen.getByText("legacy cell").closest("table")).toHaveClass("min-w-full", "text-sm");
    expect(screen.getByText("legacy cell").closest("td")).toHaveClass("px-3", "py-2", "border-r");
    expect(screen.getByText("slide text")).toHaveStyle({ fontSize: "28px" });
    expect(screen.getByText("slide text").closest("p")).toHaveClass("leading-snug");
    expect(screen.getByText("slide cell").closest("table")).toHaveClass("table-fixed", "text-[11px]");
  });
});
