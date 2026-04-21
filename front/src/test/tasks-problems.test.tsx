import { render, screen, waitFor } from "@testing-library/react";
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

test("tasks pane lists tasks and streams run output", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "listTasks").mockResolvedValue([
    { id: "npm:test", label: "npm test", command: "npm run test", source: "package.json" },
  ]);
  vi.spyOn(client, "runTaskStream").mockImplementation(async (_botAlias, taskId, onEvent) => {
    onEvent({ type: "log", text: "vitest started" });
    return {
      taskId,
      success: true,
      returnCode: 0,
      output: "vitest started\n",
      problems: [],
    };
  });

  renderWorkbench(client);

  await user.click(screen.getByRole("button", { name: "任务" }));
  expect(await screen.findByText("npm test")).toBeInTheDocument();

  await user.click(await screen.findByRole("button", { name: "运行 npm:test" }));

  expect(await screen.findByText("vitest started")).toBeInTheDocument();
  expect(client.runTaskStream).toHaveBeenCalledWith("main", "npm:test", expect.any(Function), expect.any(Object));
});

test("problems pane groups diagnostics and opens selected file", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getProblems").mockResolvedValue([
    {
      path: "src/app.ts",
      line: 12,
      column: 8,
      severity: "error",
      message: "TS2322: bad type",
      source: "tsc",
    },
  ]);
  const readSpy = vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "const value = 1;\n",
    mode: "cat",
    fileSizeBytes: 16,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  renderWorkbench(client);

  await user.click(screen.getByRole("button", { name: "问题" }));
  expect(await screen.findByText("src/app.ts")).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "打开 src/app.ts 第 12 行" }));

  await waitFor(() => expect(readSpy).toHaveBeenCalledWith("main", "src/app.ts"));
});
