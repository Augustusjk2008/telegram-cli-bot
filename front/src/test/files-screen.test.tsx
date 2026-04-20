import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FileEditorSurface } from "../components/FileEditorSurface";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, BotSummary, ChatMessage, ChatTraceDetails, CliParamsPayload, DirectoryListing, GitActionResult, GitDiffPayload, GitOverview, SessionState, SystemScript, SystemScriptResult, TunnelSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

let codemirrorMountCount = 0;

vi.mock("../utils/fileEditorLanguage", () => ({
  loadFileEditorExtensions: vi.fn(async () => []),
}));

vi.mock("@uiw/react-codemirror", async () => {
  const React = await import("react");

  return {
    default: ({
      className,
      height,
      width,
      theme,
      extensions,
      autoFocus,
    }: {
      className?: string;
      height?: string;
      width?: string;
      theme?: "light" | "dark";
      extensions?: unknown[];
      autoFocus?: boolean;
    }) => {
      const [isReady, setIsReady] = React.useState(false);
      const [instanceId] = React.useState(() => {
        codemirrorMountCount += 1;
        return `instance-${codemirrorMountCount}`;
      });
      React.useEffect(() => {
        setIsReady(true);
      }, []);

      return (
        <div
          className={className}
          data-testid="codemirror-wrapper"
          data-height={height}
          data-width={width}
          data-theme={theme}
          data-extension-count={String(extensions?.length ?? 0)}
          data-autofocus={autoFocus ? "true" : "false"}
          data-instance-id={instanceId}
        >
          {isReady ? (
            <div className="cm-editor" data-testid="codemirror-editor">
              <div className="cm-scroller" data-testid="codemirror-scroller">mock editor</div>
            </div>
          ) : null}
        </div>
      );
    },
  };
});

beforeEach(() => {
  codemirrorMountCount = 0;
  document.documentElement.dataset.theme = "deep-space";
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("editor remounts codemirror when switching files inside the same surface", async () => {
  const { rerender } = render(
    <FileEditorSurface
      path="notes.txt"
      value="first"
      onChange={() => {}}
      onSave={() => {}}
      onClose={() => {}}
      hideHeader
    />,
  );

  const firstWrapper = await screen.findByTestId("codemirror-wrapper");
  expect(firstWrapper).toHaveAttribute("data-instance-id", "instance-1");

  rerender(
    <FileEditorSurface
      path="README.md"
      value="second"
      onChange={() => {}}
      onSave={() => {}}
      onClose={() => {}}
      hideHeader
    />,
  );

  const secondWrapper = await screen.findByTestId("codemirror-wrapper");
  expect(secondWrapper).toHaveAttribute("data-instance-id", "instance-2");
});

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    login: async (): Promise<SessionState> => ({
      currentBotAlias: "main",
      currentPath: "C:\\workspace",
      isLoggedIn: true,
      canExec: true,
      canAdmin: true,
    }),
    listBots: async (): Promise<BotSummary[]> => [],
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
    }),
    listMessages: async (): Promise<ChatMessage[]> => [],
    getMessageTrace: async (): Promise<ChatTraceDetails> => ({
      traceCount: 0,
      toolCallCount: 0,
      processCount: 0,
      trace: [],
    }),
    sendMessage: async () => ({
      id: "assistant-1",
      role: "assistant" as const,
      text: "ok",
      createdAt: new Date().toISOString(),
      state: "done" as const,
    }),
    getCurrentPath: async () => "C:\\workspace",
    listFiles: async (): Promise<DirectoryListing> => ({
      workingDir: "C:\\workspace",
      entries: [
        { name: "README.md", isDir: false, size: 512, updatedAt: "2026-04-09T10:00:00Z" },
        { name: "notes.txt", isDir: false, size: 128, updatedAt: "2026-04-09T10:00:00Z" },
      ],
    }),
    changeDirectory: async () => "C:\\workspace",
    createDirectory: async () => undefined,
    deletePath: async () => undefined,
    readFile: async (_botAlias: string, filename: string) => {
      if (filename === "README.md") {
        return {
          content: [
            "# Markdown Title",
            "",
            "- item 1",
            "- item 2",
            "",
            "| Name | Value |",
            "| --- | --- |",
            "| Cell | 42 |",
            "",
            "![Architecture](assets/diagram.png)",
            "",
            "```ts",
            "const answer = 42;",
          "```",
        ].join("\n"),
          mode: "head",
          fileSizeBytes: 512,
          isFullContent: false,
        };
      }
      return {
        content: "# Raw Heading\n\n- should stay literal",
        mode: "head",
        fileSizeBytes: 128,
        isFullContent: false,
      };
    },
    readFileFull: async (_botAlias: string, filename: string) => ({
      content: `FULL:${filename}`,
      mode: "cat" as const,
      fileSizeBytes: 128,
      isFullContent: true,
    }),
    uploadFile: async () => undefined,
    downloadFile: async () => undefined,
    resetSession: async () => undefined,
    killTask: async () => "已发送终止任务请求",
    getGitProxySettings: async () => ({ port: "" }),
    updateGitProxySettings: async () => ({ port: "" }),
    updateBotWorkdir: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      lastActiveText: "运行中",
    }),
    getCliParams: async (): Promise<CliParamsPayload> => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    updateCliParam: async (): Promise<CliParamsPayload> => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    resetCliParams: async (): Promise<CliParamsPayload> => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    getTunnelStatus: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    startTunnel: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    stopTunnel: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    restartTunnel: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    restartService: async (): Promise<void> => undefined,
    getGitOverview: async (): Promise<GitOverview> => ({
      repoFound: false,
      canInit: true,
      workingDir: "C:\\workspace",
      repoPath: "",
      repoName: "",
      currentBranch: "",
      isClean: true,
      aheadCount: 0,
      behindCount: 0,
      changedFiles: [],
      recentCommits: [],
    }),
    initGitRepository: async (): Promise<GitOverview> => ({
      repoFound: true,
      canInit: false,
      workingDir: "C:\\workspace",
      repoPath: "C:\\workspace",
      repoName: "workspace",
      currentBranch: "main",
      isClean: true,
      aheadCount: 0,
      behindCount: 0,
      changedFiles: [],
      recentCommits: [],
    }),
    getGitDiff: async (): Promise<GitDiffPayload> => ({
      path: "README.md",
      staged: false,
      diff: "",
    }),
    stageGitPaths: async (): Promise<GitActionResult> => ({
      message: "已暂存",
      overview: await createClient().getGitOverview("main"),
    }),
    unstageGitPaths: async (): Promise<GitActionResult> => ({
      message: "已取消暂存",
      overview: await createClient().getGitOverview("main"),
    }),
    commitGitChanges: async (): Promise<GitActionResult> => ({
      message: "已提交",
      overview: await createClient().initGitRepository("main"),
    }),
    fetchGitRemote: async (): Promise<GitActionResult> => ({
      message: "已抓取",
      overview: await createClient().initGitRepository("main"),
    }),
    pullGitRemote: async (): Promise<GitActionResult> => ({
      message: "已拉取",
      overview: await createClient().initGitRepository("main"),
    }),
    pushGitRemote: async (): Promise<GitActionResult> => ({
      message: "已推送",
      overview: await createClient().initGitRepository("main"),
    }),
    stashGitChanges: async (): Promise<GitActionResult> => ({
      message: "已暂存工作区",
      overview: await createClient().initGitRepository("main"),
    }),
    popGitStash: async (): Promise<GitActionResult> => ({
      message: "已恢复暂存",
      overview: await createClient().initGitRepository("main"),
    }),
    listSystemScripts: async (): Promise<SystemScript[]> => [],
    runSystemScript: async (): Promise<SystemScriptResult> => ({
      scriptName: "demo",
      success: true,
      output: "ok",
    }),
    runSystemScriptStream: async (): Promise<SystemScriptResult> => ({
      scriptName: "demo",
      success: true,
      output: "ok",
    }),
    ...overrides,
  });
}

test("renders markdown files as formatted content", async () => {
  const user = userEvent.setup();
  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));

  expect(await screen.findByRole("heading", { name: "Markdown Title" })).toBeInTheDocument();
  expect(screen.getByText("item 1")).toBeInTheDocument();
  expect(screen.getByText("Cell")).toBeInTheDocument();
  expect(screen.getByText("const answer = 42;")).toBeInTheDocument();
});

test("shows markdown image paths instead of rendering images", async () => {
  const user = userEvent.setup();
  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));

  expect(await screen.findByText(/assets\/diagram\.png/)).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

test("keeps non-markdown files in plain-text preview mode", async () => {
  const user = userEvent.setup();
  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: "打开 notes.txt" }));

  expect(await screen.findByText((content) => content.includes("# Raw Heading"))).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes("- should stay literal"))).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Raw Heading" })).not.toBeInTheDocument();
});

test("can load full file content from preview modal", async () => {
  const user = userEvent.setup();
  const readFullSpy = vi.fn(async () => ({
    content: "完整内容\n第二行",
    mode: "cat" as const,
    fileSizeBytes: 128,
    isFullContent: true,
  }));
  const client = createClient();
  client.readFileFull = readFullSpy;

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "打开 notes.txt" }));
  await user.click(await screen.findByRole("button", { name: "全文读取" }));

  expect(readFullSpy).toHaveBeenCalledWith("main", "notes.txt");
  expect(await screen.findByText((content) => content.includes("完整内容"))).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
  expect(screen.getByText("已加载全文")).toBeInTheDocument();
});

test("editor mounts a full-size codemirror wrapper and autofocuses on open", async () => {
  const user = userEvent.setup();

  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: "编辑 notes.txt" }));

  const wrapper = await screen.findByTestId("codemirror-wrapper");
  expect(wrapper).toHaveClass("h-full");
  expect(wrapper).toHaveClass("min-h-0");
  expect(wrapper).toHaveClass("w-full");
  expect(wrapper).toHaveClass("min-w-0");
  expect(wrapper).toHaveAttribute("data-height", "100%");
  expect(wrapper).toHaveAttribute("data-width", "100%");
  expect(wrapper).toHaveAttribute("data-theme", "dark");
  expect(wrapper).toHaveAttribute("data-autofocus", "true");
});

test("editor switches codemirror theme mode with the app theme", async () => {
  const user = userEvent.setup();
  document.documentElement.dataset.theme = "classic";

  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: "编辑 notes.txt" }));

  const wrapper = await screen.findByTestId("codemirror-wrapper");
  expect(wrapper).toHaveAttribute("data-theme", "light");
});

test("editor uses a CodeMirror theme extension instead of mutating editor DOM styles", async () => {
  const user = userEvent.setup();

  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: "编辑 notes.txt" }));

  const wrapper = await screen.findByTestId("codemirror-wrapper");
  const editor = await screen.findByTestId("codemirror-editor");
  const scroller = await screen.findByTestId("codemirror-scroller");
  await waitFor(() => {
    expect(wrapper).toHaveAttribute("data-extension-count", "1");
  });
  expect(editor).not.toHaveAttribute("style");
  expect(scroller).not.toHaveAttribute("style");
});

test("editor uses a single flat surface instead of a nested rounded frame", async () => {
  const user = userEvent.setup();

  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: "编辑 notes.txt" }));

  const host = await screen.findByTestId("file-editor-host");
  expect(host).not.toHaveClass("rounded-2xl");
  expect(host).not.toHaveClass("border");
});

test("hides the full-read button when preview already contains the whole small file", async () => {
  const user = userEvent.setup();
  const client = createClient({
    listFiles: async (): Promise<DirectoryListing> => ({
      workingDir: "C:\\workspace",
      entries: [{ name: "tiny.txt", isDir: false, size: 18, updatedAt: "2026-04-09T10:00:00Z" }],
    }),
    readFile: async () => ({
      content: "tiny file content",
      mode: "head",
      fileSizeBytes: 18,
      isFullContent: true,
    }),
  });

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "打开 tiny.txt" }));

  expect(await screen.findByText("已加载全文")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
});

test("shows a download-only warning for files larger than 200KB", async () => {
  const user = userEvent.setup();
  const client = createClient({
    listFiles: async (): Promise<DirectoryListing> => ({
      workingDir: "C:\\workspace",
      entries: [{ name: "big.log", isDir: false, size: 205 * 1024, updatedAt: "2026-04-09T10:00:00Z" }],
    }),
    readFile: async () => ({
      content: "preview line 1\npreview line 2",
      mode: "head",
      fileSizeBytes: 205 * 1024,
      isFullContent: false,
    }),
  });

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "打开 big.log" }));

  expect(await screen.findByText("文件超过200KB，请下载后读取全文")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
});

test("home button resets the browser directory to the bot working directory", async () => {
  const user = userEvent.setup();
  const getCurrentPathSpy = vi.fn(async () => "C:\\workspace\\root");
  const changeDirectorySpy = vi.fn(async () => "C:\\workspace\\root");
  const listFilesSpy = vi
    .fn<() => Promise<DirectoryListing>>()
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace\\nested",
      entries: [{ name: "nested.txt", isDir: false }],
    })
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace\\root",
      entries: [{ name: "root.txt", isDir: false }],
    });

  render(<FilesScreen botAlias="main" client={createClient({
    getCurrentPath: getCurrentPathSpy,
    changeDirectory: changeDirectorySpy,
    listFiles: listFilesSpy,
  })} />);

  expect(await screen.findByRole("heading", { name: "main" })).toBeInTheDocument();
  expect(screen.getByText("C:\\workspace\\nested")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Home" }));

  expect(getCurrentPathSpy).toHaveBeenCalledWith("main");
  expect(changeDirectorySpy).toHaveBeenCalledWith("main", "C:\\workspace\\root");
  expect(listFilesSpy).toHaveBeenCalledTimes(2);
  expect(await screen.findByText("C:\\workspace\\root")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开 root.txt" })).toBeInTheDocument();
});

test("file rows render download before delete and reuse the existing download flow", async () => {
  const user = userEvent.setup();
  const downloadFileSpy = vi.fn(async () => undefined);

  render(<FilesScreen botAlias="main" client={createClient({ downloadFile: downloadFileSpy })} />);

  const downloadButton = await screen.findByRole("button", { name: "下载 README.md" });
  const deleteButton = screen.getByRole("button", { name: "删除 README.md" });
  const row = downloadButton.closest("li");

  expect(row).not.toBeNull();

  const buttons = within(row as HTMLLIElement).getAllByRole("button");
  expect(buttons.at(-2)).toBe(downloadButton);
  expect(buttons.at(-1)).toBe(deleteButton);

  await user.click(downloadButton);

  expect(downloadFileSpy).toHaveBeenCalledWith("main", "README.md");
});

test("can create a folder from the files screen toolbar", async () => {
  const user = userEvent.setup();
  const createDirectorySpy = vi.fn(async () => undefined);
  const listFilesSpy = vi
    .fn<() => Promise<DirectoryListing>>()
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace",
      entries: [{ name: "README.md", isDir: false }],
    })
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace",
      entries: [
        { name: "docs", isDir: true },
        { name: "README.md", isDir: false },
      ],
    });
  const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("docs");
  const client = createClient({ listFiles: listFilesSpy }) as WebBotClient & {
    createDirectory: (botAlias: string, name: string) => Promise<void>;
  };
  client.createDirectory = createDirectorySpy;

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "新建文件夹" }));

  expect(promptSpy).toHaveBeenCalledWith("请输入新文件夹名称", "");
  expect(createDirectorySpy).toHaveBeenCalledWith("main", "docs");
  expect(listFilesSpy).toHaveBeenCalledTimes(2);
  expect(await screen.findByRole("button", { name: "进入 docs" })).toBeInTheDocument();
});

test("deleting a non-empty folder requires confirmation before recursive removal", async () => {
  const user = userEvent.setup();
  const deletePathSpy = vi.fn(async () => undefined);
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  const listFilesSpy = vi
    .fn<() => Promise<DirectoryListing>>()
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace",
      entries: [{ name: "docs", isDir: true }],
    })
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace",
      entries: [],
    });
  const client = createClient({ listFiles: listFilesSpy }) as WebBotClient & {
    deletePath: (botAlias: string, path: string) => Promise<void>;
  };
  client.deletePath = deletePathSpy;

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "删除 docs" }));

  expect(confirmSpy).toHaveBeenCalledWith("确定删除文件夹 docs 吗？此操作会递归删除其中的所有内容。");
  expect(deletePathSpy).toHaveBeenCalledWith("main", "docs");
  expect(listFilesSpy).toHaveBeenCalledTimes(2);
});

test("cancelled deletion does not remove the selected file", async () => {
  const user = userEvent.setup();
  const deletePathSpy = vi.fn(async () => undefined);
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  const client = createClient({ listFiles: async () => ({
    workingDir: "C:\\workspace",
    entries: [{ name: "README.md", isDir: false }],
  }) }) as WebBotClient & {
    deletePath: (botAlias: string, path: string) => Promise<void>;
  };
  client.deletePath = deletePathSpy;

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "删除 README.md" }));

  expect(confirmSpy).toHaveBeenCalledWith("确定删除文件 README.md 吗？");
  expect(deletePathSpy).not.toHaveBeenCalled();
});
