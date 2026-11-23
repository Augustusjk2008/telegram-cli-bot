import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
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
