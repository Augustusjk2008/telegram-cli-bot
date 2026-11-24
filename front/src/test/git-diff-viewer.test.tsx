import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { GitDiffViewer, sideBySideGitDiffRows } from "../components/GitDiffViewer";

const diff = [
  "diff --git a/example.ts b/example.ts",
  "@@ -1,3 +1,3 @@",
  " unchanged",
  "-old line",
  "+new line",
  " trailing",
].join("\n");

test("aligns changed lines in the side-by-side diff rows", () => {
  const rows = sideBySideGitDiffRows(diff).filter((row) => row.type === "line");

  expect(rows).toHaveLength(3);
  expect(rows[1]).toMatchObject({
    left: { line: "old line", lineNumber: 2, kind: "delete" },
    right: { line: "new line", lineNumber: 2, kind: "add" },
  });
});

test("renders the editor diff in side-by-side mode when enabled", () => {
  render(<GitDiffViewer content={diff} enableSideBySide defaultViewMode="split" />);

  const viewer = screen.getByTestId("git-diff-content");
  expect(viewer).toHaveAttribute("data-diff-view-mode", "split");
  expect(screen.getByRole("button", { name: "并排" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("git-diff-content-side-by-side")).toContainElement(screen.getByText("old line"));
  expect(screen.getByTestId("git-diff-content-side-by-side")).toContainElement(screen.getByText("new line"));
});

function selectCode(from: Node, to: Node) {
  const range = document.createRange();
  range.setStart(from, 0);
  range.setEnd(to, to.textContent!.length);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent(document, new Event("selectionchange"));
}

const source = { path: "src/example.ts", staged: true };

test.each([
  ["@@ -8,0 +9,2 @@\n+  added\n+", "right", "新 9–10 行", "+  added\n+"],
  ["@@ -8,2 +9,0 @@\n-  deleted\n-", "left", "旧 8–9 行", "-  deleted\n-"],
  ["@@ -8 +9 @@\n--- old header text\n+++ new header text", "right", "新 9 行", "+++ new header text"],
  ["@@ -8,2 +9,3 @@\n-old\n-last\n+1\n+2\n+3", "right", "新 9–11 行", "+1\n+2\n+3"],
  ["@@ -8,2 +9,3 @@\n-old\n-last\n+1\n+2\n+3", "left", "旧 8–9 行", "-old\n-last"],
])("quotes complete %s lines from the selected column", (content, side, location, expected) => {
  const onQuote = vi.fn();
  const { container } = render(<GitDiffViewer content={content} source={source} onQuote={onQuote} enableSideBySide defaultViewMode="split" />);
  const code = container.querySelectorAll(`[data-diff-side="${side}"]:not([data-diff-kind="empty"]) [data-diff-code]`);
  selectCode(code[0].firstChild!, code[code.length - 1].firstChild!);
  fireEvent.click(screen.getByRole("button", { name: "引用到聊天" }));
  expect(onQuote).toHaveBeenCalledExactlyOnceWith(`src/example.ts · 已暂存 Diff · ${location}\n\`\`\`diff\n${expected}\n\`\`\``);
});

test("a refreshed diff and a mode switch discard the old selection; a disabled chat cannot receive a quote", () => {
  const view = (snapshot: typeof source) => <GitDiffViewer content={diff} source={snapshot} enableSideBySide defaultViewMode="split" />;
  const { rerender } = render(view(source));
  const select = () => selectCode(screen.getByText("old line").firstChild!, screen.getByText("new line").firstChild!);
  select();
  expect(screen.getByRole("button", { name: "引用到聊天" })).toBeDisabled();
  rerender(view({ ...source }));
  expect(screen.queryByRole("button", { name: "引用到聊天" })).toBeNull();
  select();
  fireEvent.click(screen.getByRole("button", { name: "全文" }));
  fireEvent.click(screen.getByRole("button", { name: "并排" }));
  expect(screen.queryByRole("button", { name: "引用到聊天" })).toBeNull();
});
