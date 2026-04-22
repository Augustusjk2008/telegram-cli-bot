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

function expectFileIcon(fileName: string, iconKind: string) {
  const button = screen.getByRole("button", { name: `打开 ${fileName}` });
  const iconKinds = Array.from(button.querySelectorAll("[data-icon]")).map((icon) => icon.getAttribute("data-icon"));
  expect(iconKinds).toContain(iconKind);
}

function expectFileIconNode(fileName: string, iconKind: string) {
  const button = screen.getByRole("button", { name: `打开 ${fileName}` });
  const icon = button.querySelector(`[data-icon="${iconKind}"]`);
  expect(icon).not.toBeNull();
  return icon as HTMLElement;
}

test("directory click expands the tree without changing the working directory", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
    if (!path || path === "/workspace") {
      return {
        workingDir: "/workspace",
        entries: [
          { name: "docs", isDir: true },
          { name: "README.md", isDir: false, size: 12 },
        ],
      };
    }
    if (path === "/workspace/docs") {
      return {
        workingDir: "/workspace/docs",
        entries: [
          { name: "project-plan.md", isDir: false, size: 24 },
        ],
      };
    }
    return {
      workingDir: path || "/workspace",
      entries: [],
    };
  });
  const changeDirectorySpy = vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await screen.findByText("README.md");
  const callsBeforeToggle = changeDirectorySpy.mock.calls.length;

  await user.click(screen.getByRole("button", { name: "展开 docs" }));

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "打开 docs/project-plan.md" })).toBeInTheDocument();
  });
  expect(changeDirectorySpy).toHaveBeenCalledTimes(callsBeforeToggle);
});

test("tree can hand a directory off to embedded settings as the next workdir target", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [
      { name: "docs", isDir: true },
      { name: "README.md", isDir: false, size: 12 },
    ],
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await screen.findByText("README.md");
  expect(screen.queryByRole("button", { name: "在终端中打开 docs" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "设 docs 为 Bot 工作目录" })).not.toBeInTheDocument();
  fireEvent.contextMenu(screen.getByRole("button", { name: "展开 docs" }));
  await user.click(await screen.findByRole("button", { name: "设为工作目录" }));

  expect(await screen.findByLabelText("工作目录")).toHaveValue("/workspace/docs");
});

