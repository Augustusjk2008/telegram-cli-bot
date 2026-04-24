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

function createDragData(path: string) {
  const store = new Map<string, string>([["application/x-tcb-file-path", path]]);
  return {
    types: ["application/x-tcb-file-path", "text/plain"],
    effectAllowed: "move",
    dropEffect: "move",
    setData: vi.fn((type: string, value: string) => {
      store.set(type, value);
    }),
    getData: vi.fn((type: string) => store.get(type) || ""),
    files: [],
  };
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

test("file context menu copies a sibling file", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let rootEntries = [
    { name: "docs", isDir: true },
    { name: "README.md", isDir: false, size: 12 },
  ];

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => ({
    workingDir: path || "/workspace",
    entries: !path || path === "/workspace" ? rootEntries : [],
  }));
  const copyPath = vi.spyOn(client, "copyPath").mockImplementation(async (_botAlias, path) => {
    rootEntries = [
      ...rootEntries,
      { name: "README 副本.md", isDir: false, size: 12 },
    ];
    return {
      sourcePath: path,
      path: "README 副本.md",
      fileSizeBytes: 12,
      lastModifiedNs: "2",
    };
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

  await screen.findByRole("button", { name: "打开 README.md" });
  fireEvent.contextMenu(screen.getByRole("button", { name: "打开 README.md" }));
  await user.click(await screen.findByRole("button", { name: "复制" }));

  expect(copyPath).toHaveBeenCalledWith("main", "README.md");
  expect(await screen.findByRole("button", { name: "打开 README 副本.md" })).toBeInTheDocument();
});

test("dragging a file onto a folder moves it into that folder", async () => {
  const client = new MockWebBotClient();
  let rootEntries = [
    { name: "docs", isDir: true },
    { name: "README.md", isDir: false, size: 12 },
  ];
  let docsEntries: Array<{ name: string; isDir: boolean; size?: number }> = [];

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
    if (!path || path === "/workspace") {
      return { workingDir: "/workspace", entries: rootEntries };
    }
    if (path === "/workspace/docs") {
      return { workingDir: "/workspace/docs", entries: docsEntries };
    }
    return { workingDir: path || "/workspace", entries: [] };
  });
  const movePath = vi.spyOn(client, "movePath").mockImplementation(async (_botAlias, path, targetParentPath) => {
    rootEntries = rootEntries.filter((entry) => entry.name !== "README.md");
    docsEntries = [{ name: "README.md", isDir: false, size: 12 }];
    return {
      oldPath: path,
      path: `${targetParentPath}/README.md`,
    };
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

  const fileButton = await screen.findByRole("button", { name: "打开 README.md" });
  const folderButton = screen.getByRole("button", { name: "展开 docs" });
  const dataTransfer = createDragData("README.md");

  fireEvent.dragStart(fileButton, { dataTransfer });
  fireEvent.dragOver(folderButton, { dataTransfer });
  fireEvent.drop(folderButton, { dataTransfer });

  await waitFor(() => {
    expect(movePath).toHaveBeenCalledWith("main", "README.md", "docs");
  });
  expect(await screen.findByRole("button", { name: "打开 docs/README.md" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "打开 README.md" })).not.toBeInTheDocument();
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

test("workspace open reveals file tree through one backend request", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [{ name: "src", isDir: true }],
  });
  vi.spyOn(client, "quickOpenWorkspace").mockResolvedValue({
    items: [{ path: "src/nested/api.py", score: 1000 }],
  });
  const revealFileTreePath = vi.fn(async () => ({
    rootPath: "/workspace",
    highlightPath: "src/nested/api.py",
    expandedPaths: ["src", "src/nested"],
    branches: {
      "": [{ name: "src", isDir: true }],
      src: [{ name: "nested", isDir: true }],
      "src/nested": [{ name: "api.py", isDir: false, size: 12 }],
    },
  }));
  Object.assign(client, { revealFileTreePath });

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

  await screen.findByRole("button", { name: "展开 src" });
  fireEvent.keyDown(window, { key: "p", ctrlKey: true });
  await user.type(await screen.findByRole("textbox", { name: "快速打开文件" }), "api");
  await user.click(await screen.findByRole("button", { name: "打开 src/nested/api.py" }));

  await waitFor(() => {
    expect(revealFileTreePath).toHaveBeenCalledTimes(1);
  });
  expect(revealFileTreePath).toHaveBeenCalledWith("main", "src/nested/api.py");
});

test("large file tree renders only visible rows", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: Array.from({ length: 500 }, (_, index) => ({
      name: `file-${String(index).padStart(3, "0")}.ts`,
      isDir: false,
      size: 12,
    })),
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

  await screen.findByRole("button", { name: "打开 file-000.ts" });

  expect(screen.getAllByRole("button", { name: /^打开 file-/ }).length).toBeLessThanOrEqual(80);
});
