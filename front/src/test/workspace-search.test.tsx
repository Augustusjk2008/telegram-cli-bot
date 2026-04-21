import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function renderWorkbench(client: MockWebBotClient) {
  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );
}

test("ctrl p opens quick picker and selected file in editor", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "quickOpenWorkspace").mockResolvedValue({
    items: [{ path: "src/api_service.py", score: 1120 }],
  });
  const readSpy = vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "x = 1\n",
    mode: "cat",
    fileSizeBytes: 6,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  renderWorkbench(client);

  fireEvent.keyDown(window, { key: "p", ctrlKey: true });
  await user.type(await screen.findByLabelText("快速打开文件"), "api");
  await user.click(await screen.findByRole("button", { name: "打开 src/api_service.py" }));

  await waitFor(() => expect(readSpy).toHaveBeenCalledWith("main", "src/api_service.py"));
  expect(await screen.findByRole("tab", { name: "api_service.py" })).toBeInTheDocument();
});

test("search pane opens from shortcut and result click opens file", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "searchWorkspace").mockResolvedValue({
    items: [{
      path: "src/main.py",
      line: 3,
      column: 9,
      preview: "needle = True",
    }],
  });
  const readSpy = vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "needle = True\n",
    mode: "cat",
    fileSizeBytes: 14,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  renderWorkbench(client);

  fireEvent.keyDown(window, { key: "F", ctrlKey: true, shiftKey: true });
  await user.type(await screen.findByLabelText("全文搜索"), "needle");
  await user.click(await screen.findByRole("button", { name: "打开 src/main.py 第 3 行" }));

  await waitFor(() => expect(readSpy).toHaveBeenCalledWith("main", "src/main.py"));
});

test("outline pane follows active editor file", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "quickOpenWorkspace").mockResolvedValue({
    items: [{ path: "src/app.py", score: 1100 }],
  });
  vi.spyOn(client, "getWorkspaceOutline").mockResolvedValue({
    items: [
      { name: "App", kind: "class", line: 1 },
      { name: "run", kind: "function", line: 2 },
    ],
  });
  vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "class App:\n    def run(self):\n        pass\n",
    mode: "cat",
    fileSizeBytes: 42,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  renderWorkbench(client);

  fireEvent.keyDown(window, { key: "p", ctrlKey: true });
  await user.type(await screen.findByLabelText("快速打开文件"), "app");
  await user.click(await screen.findByRole("button", { name: "打开 src/app.py" }));
  await user.click(await screen.findByRole("button", { name: "大纲" }));

  expect(await screen.findByRole("button", { name: "run function 第 2 行" })).toBeInTheDocument();
  expect(client.getWorkspaceOutline).toHaveBeenCalledWith("main", "src/app.py");
});
