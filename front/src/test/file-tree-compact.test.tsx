import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileEntry } from "../services/types";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function renderWorkbench(listings: Record<string, FileEntry[]>, props: { canBrowseExternalPaths?: boolean } = {}) {
  const client = new MockWebBotClient();
  const list = vi.spyOn(client, "listFiles").mockImplementation(async (_alias, path) => ({
    workingDir: path || "/workspace",
    entries: listings[path || "/workspace"] || [],
  }));
  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} {...props} />
    </PersistentTerminalProvider>,
  );
  return { client, list };
}

test("a listed single-child chain is one row that opens its innermost directory", async () => {
  const { list } = renderWorkbench({
    "/workspace": [
      { name: "java", isDir: true, childCount: 1, compactChain: [{ name: "com", childCount: 1 }, { name: "acme", childCount: 2 }] },
      { name: "README.md", isDir: false },
    ],
    "/workspace/java/com/acme": [{ name: "Main.java", isDir: false }, { name: "Util.java", isDir: false }],
  });

  const row = await screen.findByRole("button", { name: "展开 java/com/acme" });
  expect(row).toHaveTextContent("java/com/acme");
  expect(screen.queryByRole("button", { name: "展开 java" })).not.toBeInTheDocument();
  list.mockClear();

  fireEvent.click(row);
  expect(await screen.findByRole("button", { name: "打开 java/com/acme/Main.java" })).toBeInTheDocument();
  expect(list.mock.calls.map((call) => call[1])).toEqual(["/workspace/java/com/acme"]);

  // Each name stays reachable: a right click on an outer name acts on that directory.
  fireEvent.contextMenu(screen.getByText("com"));
  fireEvent.click(await screen.findByRole("button", { name: "改名" }));
  expect(await screen.findByLabelText("名称")).toHaveValue("com");
});

test("compact rows can be switched off and .git stays hidden until asked for", async () => {
  renderWorkbench({
    "/workspace": [
      { name: ".git", isDir: true, childCount: 9 },
      { name: "java", isDir: true, childCount: 1, compactChain: [{ name: "com", childCount: 3 }] },
    ],
  });

  await screen.findByRole("button", { name: "展开 java/com" });
  expect(screen.queryByRole("button", { name: "展开 .git" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "更多文件操作" }));
  fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "显示 .git" }));
  expect(await screen.findByRole("button", { name: "展开 .git" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "更多文件操作" }));
  fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "合并单一子文件夹" }));
  expect(await screen.findByRole("button", { name: "展开 java" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "展开 java/com" })).not.toBeInTheDocument();
});

test("the path jump bar opens from the menu and closes after a jump", async () => {
  const { client, list } = renderWorkbench(
    { "/workspace": [{ name: "README.md", isDir: false }], "/srv/data": [{ name: "notes.txt", isDir: false }] },
    { canBrowseExternalPaths: true },
  );
  vi.spyOn(client, "revealFileTreePath").mockRejectedValue(new Error("unused"));

  await screen.findByRole("button", { name: "打开 README.md" });
  expect(screen.queryByLabelText("跳转到绝对目录")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "更多文件操作" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "跳转到路径…" }));
  const input = screen.getByLabelText("跳转到绝对目录");
  expect(input).toHaveFocus();

  fireEvent.change(input, { target: { value: "/srv/data" } });
  fireEvent.click(screen.getByRole("button", { name: "跳转" }));
  await waitFor(() => expect(list).toHaveBeenCalledWith("main", "/srv/data", expect.anything()));
  await waitFor(() => expect(screen.queryByLabelText("跳转到绝对目录")).not.toBeInTheDocument());
});
