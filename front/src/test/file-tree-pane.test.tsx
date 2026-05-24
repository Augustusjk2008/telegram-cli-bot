import type { ReactElement } from "react";
import { fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

function render(ui: ReactElement) {
  const client = ((ui.props as { client?: MockWebBotClient }).client) || new MockWebBotClient();
  return rtlRender(
    <PersistentTerminalProvider client={client}>
      {ui}
    </PersistentTerminalProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function mockClipboardWrite() {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

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

function expectTreeRowSelected(path: string, selected = true) {
  const row = document.querySelector(`[data-tree-path="${path}"]`);
  expect(row).not.toBeNull();
  expect(row).toHaveAttribute("data-selected", selected ? "true" : "false");
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

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

test("refresh shows the root before restored child branches finish loading", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const docsRefresh = createDeferred<Awaited<ReturnType<MockWebBotClient["listFiles"]>>>();
  let refreshStarted = false;

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
    if (!path || path === "/workspace") {
      return {
        workingDir: "/workspace",
        entries: [
          { name: "docs", isDir: true },
          { name: refreshStarted ? "after-refresh.txt" : "before-refresh.txt", isDir: false, size: 12 },
        ],
      };
    }
    if (path === "/workspace/docs") {
      if (refreshStarted) {
        return docsRefresh.promise;
      }
      return {
        workingDir: "/workspace/docs",
        entries: [{ name: "ready.md", isDir: false, size: 24 }],
      };
    }
    return { workingDir: path || "/workspace", entries: [] };
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

  await user.click(await screen.findByRole("button", { name: "展开 docs" }));
  expect(await screen.findByRole("button", { name: "打开 docs/ready.md" })).toBeInTheDocument();

  refreshStarted = true;
  await user.click(screen.getByRole("button", { name: "刷新文件树" }));

  expect(await screen.findByRole("button", { name: "打开 after-refresh.txt" })).toBeInTheDocument();
  expect(screen.getByText("加载中...")).toBeInTheDocument();

  docsRefresh.resolve({
    workingDir: "/workspace/docs",
    entries: [{ name: "after.md", isDir: false, size: 24 }],
  });
  expect(await screen.findByRole("button", { name: "打开 docs/after.md" })).toBeInTheDocument();
});

test("clicking a branch while background restore is loading reuses the same request", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const docsRefresh = createDeferred<Awaited<ReturnType<MockWebBotClient["listFiles"]>>>();
  let refreshStarted = false;

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  const listFilesSpy = vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
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
      if (refreshStarted) {
        return docsRefresh.promise;
      }
      return {
        workingDir: "/workspace/docs",
        entries: [{ name: "ready.md", isDir: false, size: 24 }],
      };
    }
    return { workingDir: path || "/workspace", entries: [] };
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

  await user.click(await screen.findByRole("button", { name: "展开 docs" }));
  await screen.findByRole("button", { name: "打开 docs/ready.md" });

  refreshStarted = true;
  await user.click(screen.getByRole("button", { name: "刷新文件树" }));
  await screen.findByRole("button", { name: "打开 README.md" });
  await user.click(screen.getByRole("button", { name: "收起 docs" }));
  await user.click(screen.getByRole("button", { name: "展开 docs" }));

  expect(listFilesSpy.mock.calls.filter(([, path]) => path === "/workspace/docs")).toHaveLength(2);

  docsRefresh.resolve({
    workingDir: "/workspace/docs",
    entries: [{ name: "after.md", isDir: false, size: 24 }],
  });
  expect(await screen.findByRole("button", { name: "打开 docs/after.md" })).toBeInTheDocument();
  expect(listFilesSpy.mock.calls.filter(([, path]) => path === "/workspace/docs")).toHaveLength(2);
});

test("forced branch refresh after file creation wins over stale background restore", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const staleDocsRefresh = createDeferred<Awaited<ReturnType<MockWebBotClient["listFiles"]>>>();
  let refreshStarted = false;
  let docsEntries = [{ name: "old.md", isDir: false, size: 12 }];

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
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
      if (refreshStarted) {
        refreshStarted = false;
        return staleDocsRefresh.promise;
      }
      return {
        workingDir: "/workspace/docs",
        entries: docsEntries,
      };
    }
    return { workingDir: path || "/workspace", entries: [] };
  });
  vi.spyOn(client, "createTextFile").mockImplementation(async (_botAlias, filename) => {
    docsEntries = [{ name: filename, isDir: false, size: 0 }];
    return {
      path: `docs/${filename}`,
      fileSizeBytes: 0,
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

  await user.click(await screen.findByRole("button", { name: "展开 docs" }));
  await screen.findByRole("button", { name: "打开 docs/old.md" });

  refreshStarted = true;
  await user.click(screen.getByRole("button", { name: "刷新文件树" }));
  await screen.findByText("加载中...");
  await user.click(screen.getByRole("button", { name: "新建文件" }));
  await user.type(await screen.findByRole("textbox", { name: "文件名" }), "new.md");
  await user.click(screen.getByRole("button", { name: "创建" }));

  expect(await screen.findByRole("button", { name: "打开 docs/new.md" })).toBeInTheDocument();

  staleDocsRefresh.resolve({
    workingDir: "/workspace/docs",
    entries: [{ name: "stale.md", isDir: false, size: 12 }],
  });

  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "打开 docs/stale.md" })).not.toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "打开 docs/new.md" })).toBeInTheDocument();
});

test("stale background branch results do not overwrite after switching bots", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const oldDocsRefresh = createDeferred<Awaited<ReturnType<MockWebBotClient["listFiles"]>>>();
  let refreshStarted = false;

  vi.spyOn(client, "getCurrentPath").mockImplementation(async (botAlias) => (
    botAlias === "team2" ? "/team2" : "/workspace"
  ));
  vi.spyOn(client, "changeDirectory").mockImplementation(async (botAlias, path) => (
    botAlias === "team2" ? "/team2" : path
  ));
  vi.spyOn(client, "listFiles").mockImplementation(async (botAlias, path) => {
    if (botAlias === "team2") {
      if (!path || path === "/team2") {
        return {
          workingDir: "/team2",
          entries: [{ name: "docs", isDir: true }],
        };
      }
      if (path === "/team2/docs") {
        return {
          workingDir: "/team2/docs",
          entries: [{ name: "new-bot.md", isDir: false, size: 12 }],
        };
      }
    }

    if (!path || path === "/workspace") {
      return {
        workingDir: "/workspace",
        entries: [{ name: "docs", isDir: true }],
      };
    }
    if (path === "/workspace/docs") {
      if (refreshStarted) {
        return oldDocsRefresh.promise;
      }
      return {
        workingDir: "/workspace/docs",
        entries: [{ name: "old-bot-ready.md", isDir: false, size: 12 }],
      };
    }
    return { workingDir: path || "/workspace", entries: [] };
  });

  const view = render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "展开 docs" }));
  await screen.findByRole("button", { name: "打开 docs/old-bot-ready.md" });

  refreshStarted = true;
  await user.click(screen.getByRole("button", { name: "刷新文件树" }));
  await screen.findByText("加载中...");

  view.rerender(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench
        authToken="123"
        botAlias="team2"
        client={client}
        viewMode="desktop"
        onViewModeChange={() => {}}
        onOpenBotSwitcher={() => {}}
      />
    </PersistentTerminalProvider>,
  );

  await user.click(await screen.findByRole("button", { name: "展开 docs" }));
  expect(await screen.findByRole("button", { name: "打开 docs/new-bot.md" })).toBeInTheDocument();

  oldDocsRefresh.resolve({
    workingDir: "/workspace/docs",
    entries: [{ name: "old-bot-late.md", isDir: false, size: 12 }],
  });

  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "打开 docs/old-bot-late.md" })).not.toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "打开 docs/new-bot.md" })).toBeInTheDocument();
});

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

test("desktop file tree home button resets to the bot working directory", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const getCurrentPathSpy = vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  const changeDirectorySpy = vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  const listFilesSpy = vi
    .spyOn(client, "listFiles")
    .mockResolvedValueOnce({
      workingDir: "/workspace/nested",
      entries: [{ name: "nested.txt", isDir: false, size: 12 }],
    })
    .mockResolvedValueOnce({
      workingDir: "/workspace",
      entries: [{ name: "root.txt", isDir: false, size: 12 }],
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

  expect(await screen.findByText("/workspace/nested")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Home" }));

  await waitFor(() => {
    expect(getCurrentPathSpy).toHaveBeenCalledWith("main");
  });
  expect(changeDirectorySpy).toHaveBeenCalledWith("main", "/workspace");
  expect(listFilesSpy).toHaveBeenCalledTimes(2);
  expect(await screen.findByText("/workspace")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开 root.txt" })).toBeInTheDocument();
});

test("clicking desktop file tree rows marks exactly one selected row", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
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
    return { workingDir: path || "/workspace", entries: [] };
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

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  expectTreeRowSelected("README.md");
  expectTreeRowSelected("docs", false);

  await user.click(screen.getByRole("button", { name: "展开 docs" }));
  expectTreeRowSelected("docs");
  expectTreeRowSelected("README.md", false);
});

test("right-clicking a desktop file tree row selects the menu target", async () => {
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

  const fileButton = await screen.findByRole("button", { name: "打开 README.md" });
  fireEvent.contextMenu(fileButton);

  expectTreeRowSelected("README.md");
  expect(await screen.findByRole("menu", { name: "文件树菜单" })).toBeInTheDocument();
});

test("new file is created inside the selected directory", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const rootEntries = [
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
  const createTextFile = vi.spyOn(client, "createTextFile").mockImplementation(async (_botAlias, filename, _content, parentPath) => {
    docsEntries = [{ name: filename, isDir: false, size: 0 }];
    return {
      path: `docs/${filename}`,
      fileSizeBytes: 0,
      lastModifiedNs: "1",
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

  await user.click(await screen.findByRole("button", { name: "展开 docs" }));
  await user.click(screen.getByRole("button", { name: "新建文件" }));
  await user.type(await screen.findByRole("textbox", { name: "文件名" }), "note.md");
  await user.click(screen.getByRole("button", { name: "创建" }));

  await waitFor(() => {
    expect(createTextFile).toHaveBeenCalledWith("main", "note.md", "", "/workspace/docs");
  });
  expect(await screen.findByRole("button", { name: "打开 docs/note.md" })).toBeInTheDocument();
  expectTreeRowSelected("docs/note.md");
});

test("new directory is created inside the selected directory", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const rootEntries = [
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
  const createDirectory = vi.spyOn(client, "createDirectory").mockImplementation(async (_botAlias, name) => {
    docsEntries = [{ name, isDir: true }];
  });
  vi.spyOn(window, "prompt").mockReturnValue("assets");

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

  await user.click(await screen.findByRole("button", { name: "展开 docs" }));
  await user.click(screen.getByRole("button", { name: "新建文件夹" }));

  await waitFor(() => {
    expect(createDirectory).toHaveBeenCalledWith("main", "assets", "/workspace/docs");
  });
  expect(await screen.findByRole("button", { name: "展开 docs/assets" })).toBeInTheDocument();
  expectTreeRowSelected("docs/assets");
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
  expectTreeRowSelected("README 副本.md");
});

test("file context menu copies the absolute file path", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const writeText = mockClipboardWrite();

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [
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

  await screen.findByRole("button", { name: "打开 README.md" });
  fireEvent.contextMenu(screen.getByRole("button", { name: "打开 README.md" }));
  await user.click(await screen.findByRole("button", { name: "复制路径" }));

  expect(writeText).toHaveBeenCalledWith("/workspace/README.md");
});

test("directory context menu copies the absolute directory path", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const writeText = mockClipboardWrite();

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [
      { name: "docs", isDir: true },
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

  await screen.findByRole("button", { name: "展开 docs" });
  fireEvent.contextMenu(screen.getByRole("button", { name: "展开 docs" }));
  await user.click(await screen.findByRole("button", { name: "复制路径" }));

  expect(writeText).toHaveBeenCalledWith("/workspace/docs");
});

test("deleting a selected file moves selection to a sibling", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let rootEntries = [
    { name: "docs", isDir: true },
    { name: "README.md", isDir: false, size: 12 },
    { name: "package.json", isDir: false, size: 24 },
  ];

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => ({
    workingDir: path || "/workspace",
    entries: !path || path === "/workspace" ? rootEntries : [],
  }));
  vi.spyOn(client, "deletePath").mockImplementation(async (_botAlias, path) => {
    rootEntries = rootEntries.filter((entry) => entry.name !== path);
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);

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

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  fireEvent.contextMenu(screen.getByRole("button", { name: "打开 README.md" }));
  await user.click(await screen.findByRole("button", { name: "删除" }));

  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "打开 README.md" })).not.toBeInTheDocument();
  });
  expectTreeRowSelected("package.json");
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
  expectTreeRowSelected("docs/README.md");
  expect(screen.queryByRole("button", { name: "打开 README.md" })).not.toBeInTheDocument();
});

test("dragging a folder onto another folder moves it into that folder", async () => {
  const client = new MockWebBotClient();
  let rootEntries = [
    { name: "docs", isDir: true },
    { name: "src", isDir: true },
  ];
  let docsEntries: Array<{ name: string; isDir: boolean; size?: number }> = [];
  let srcEntries: Array<{ name: string; isDir: boolean; size?: number }> = [
    { name: "main.ts", isDir: false, size: 12 },
  ];

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
    if (!path || path === "/workspace") {
      return { workingDir: "/workspace", entries: rootEntries };
    }
    if (path === "/workspace/docs") {
      return { workingDir: "/workspace/docs", entries: docsEntries };
    }
    if (path === "/workspace/docs/src") {
      return { workingDir: "/workspace/docs/src", entries: srcEntries };
    }
    return { workingDir: path || "/workspace", entries: [] };
  });
  const movePath = vi.spyOn(client, "movePath").mockImplementation(async (_botAlias, path, targetParentPath) => {
    rootEntries = rootEntries.filter((entry) => entry.name !== "src");
    docsEntries = [{ name: "src", isDir: true }];
    return {
      oldPath: path,
      path: `${targetParentPath}/src`,
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

  const sourceFolderButton = await screen.findByRole("button", { name: "展开 src" });
  const targetFolderButton = screen.getByRole("button", { name: "展开 docs" });
  const dataTransfer = createDragData("src");

  fireEvent.dragStart(sourceFolderButton, { dataTransfer });
  fireEvent.dragOver(targetFolderButton, { dataTransfer });
  fireEvent.drop(targetFolderButton, { dataTransfer });

  await waitFor(() => {
    expect(movePath).toHaveBeenCalledWith("main", "src", "docs");
  });
  expect(await screen.findByRole("button", { name: "展开 docs/src" })).toBeInTheDocument();
  expectTreeRowSelected("docs/src");
  expect(screen.queryByRole("button", { name: "展开 src" })).not.toBeInTheDocument();
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
  await waitFor(() => {
    expectTreeRowSelected("src/nested/api.py");
  });
});

test("refresh clears selection when the selected file disappears", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let rootEntries = [
    { name: "README.md", isDir: false, size: 12 },
  ];

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => ({
    workingDir: path || "/workspace",
    entries: !path || path === "/workspace" ? rootEntries : [],
  }));

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

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  expectTreeRowSelected("README.md");

  rootEntries = [];
  await user.click(screen.getByRole("button", { name: "刷新文件树" }));

  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "打开 README.md" })).not.toBeInTheDocument();
  });
  expect(document.querySelector('[data-selected="true"]')).toBeNull();
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
