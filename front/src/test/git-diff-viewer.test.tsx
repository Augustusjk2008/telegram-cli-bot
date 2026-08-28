import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { GitDiffViewer, visibleGitDiffLines } from "../components/GitDiffViewer";

test("maps changed and unchanged rows to source line numbers", () => {
  const lines = visibleGitDiffLines([
    "@@ -10,2 +20,3 @@",
    " context",
    "-old line",
    "\\ No newline at end of file",
    "+new line",
    "+another new line",
    "@@ -30 +40 @@",
    "-old line in next hunk",
    "+new line in next hunk",
  ].join("\n"));

  expect(lines.map(({ kind, lineNumber }) => ({ kind, lineNumber }))).toEqual([
    { kind: "context", lineNumber: 20 },
    { kind: "delete", lineNumber: 11 },
    { kind: "add", lineNumber: 21 },
    { kind: "add", lineNumber: 22 },
    { kind: "delete", lineNumber: 30 },
    { kind: "add", lineNumber: 40 },
  ]);
});

test("renders unchanged lines without add or delete colors", () => {
  render(
    <GitDiffViewer
      testId="viewer"
      content={[
        "diff --git a/src/app.ts b/src/app.ts",
        "index abc..def 100644",
        "--- a/src/app.ts",
        "+++ b/src/app.ts",
        "@@ -1,3 +1,3 @@",
        " unchanged line",
        "-old line",
        "+new line",
      ].join("\n")}
    />,
  );

  const viewer = screen.getByTestId("viewer");
  expect(within(viewer).queryByText(/diff --git/)).not.toBeInTheDocument();
  expect(within(viewer).queryByText(/@@/)).not.toBeInTheDocument();
  const contextRow = within(viewer).getByText("unchanged line").closest("[data-diff-kind]");
  expect(contextRow).toHaveAttribute("data-diff-kind", "context");
  expect(contextRow).not.toHaveClass("bg-red-50", "text-red-700");
  expect(contextRow).not.toHaveClass("bg-emerald-50", "text-emerald-700");

  const rows = within(viewer).getAllByTestId("git-diff-line");
  expect(rows).toHaveLength(3);
  expect(rows[1]).toHaveAttribute("data-diff-kind", "delete");
  expect(rows[1]).toHaveClass("bg-red-50", "text-red-700");
  expect(rows[1]).toHaveTextContent("-old line");
  expect(rows[2]).toHaveAttribute("data-diff-kind", "add");
  expect(rows[2]).toHaveClass("bg-emerald-50", "text-emerald-700");
  expect(rows[2]).toHaveTextContent("+new line");
});

test("shows a neutral empty state when diff has no file lines", () => {
  render(<GitDiffViewer testId="viewer" content="" />);
  expect(screen.getByText("无可显示的内容")).toBeInTheDocument();
  expect(screen.queryByTestId("git-diff-line")).not.toBeInTheDocument();
});
