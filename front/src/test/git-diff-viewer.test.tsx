import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { GitDiffViewer } from "../components/GitDiffViewer";

test("renders only added and deleted diff lines", () => {
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
  expect(within(viewer).queryByText(" unchanged line")).not.toBeInTheDocument();

  const rows = within(viewer).getAllByTestId("git-diff-line");
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveAttribute("data-diff-kind", "delete");
  expect(rows[0]).toHaveClass("bg-red-50", "text-red-700");
  expect(rows[0]).toHaveTextContent("-old line");
  expect(rows[1]).toHaveAttribute("data-diff-kind", "add");
  expect(rows[1]).toHaveClass("bg-emerald-50", "text-emerald-700");
  expect(rows[1]).toHaveTextContent("+new line");
});

test("shows a neutral empty state when diff has no add or delete lines", () => {
  render(<GitDiffViewer testId="viewer" content={"@@ -1 +1 @@\n unchanged"} />);
  expect(screen.getByText("无新增或删除内容")).toBeInTheDocument();
  expect(screen.queryByTestId("git-diff-line")).not.toBeInTheDocument();
});
