import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FileEditorSurface } from "../components/FileEditorSurface";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, BotSummary, ChatMessage, ChatTraceDetails, CliParamsPayload, DirectoryListing, FileDownloadProgress, GitActionResult, GitDiffPayload, GitOverview, SessionState, TunnelSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { loadFileEditorExtensions } from "../utils/fileEditorLanguage";

let codemirrorMountCount = 0;
let codemirrorExtensionVersionCount = 0;
let codemirrorBasicSetupVersionCount = 0;
let lastExtensionsRef: unknown[] | undefined;
let lastBasicSetupRef: unknown;

const noop = () => {};
const mockedLoadFileEditorExtensions = vi.mocked(loadFileEditorExtensions);

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

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
      basicSetup,
    }: {
      className?: string;
      height?: string;
      width?: string;
      theme?: "light" | "dark";
      extensions?: unknown[];
      autoFocus?: boolean;
      basicSetup?: unknown;
    }) => {
      const [isReady, setIsReady] = React.useState(false);
      const [instanceId] = React.useState(() => {
        codemirrorMountCount += 1;
        return `instance-${codemirrorMountCount}`;
      });

      if (lastExtensionsRef !== extensions) {
        lastExtensionsRef = extensions;
        codemirrorExtensionVersionCount += 1;
      }
      if (lastBasicSetupRef !== basicSetup) {
        lastBasicSetupRef = basicSetup;
        codemirrorBasicSetupVersionCount += 1;
      }

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
          data-extension-version-count={String(codemirrorExtensionVersionCount)}
          data-basicsetup-version-count={String(codemirrorBasicSetupVersionCount)}
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
  codemirrorExtensionVersionCount = 0;
  codemirrorBasicSetupVersionCount = 0;
  lastExtensionsRef = undefined;
  lastBasicSetupRef = undefined;
  mockedLoadFileEditorExtensions.mockClear();
  mockedLoadFileEditorExtensions.mockResolvedValue([]);
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


function StableRenderHarness() {
  const [tick, setTick] = useState(0);

  return (
    <div>
      <button type="button" onClick={() => setTick((value) => value + 1)}>
        rerender
      </button>
      <span data-testid="tick">{tick}</span>
      <FileEditorSurface
        path="README.md"
        value="### Heading"
        onChange={noop}
        onSave={noop}
        onClose={noop}
        hideHeader
      />
    </div>
  );
}


test("structureOnly hides editing and preview-only actions", async () => {
  const user = userEvent.setup();

  render(<FilesScreen botAlias="main" client={createClient()} structureOnly />);

  expect(await screen.findByRole("button", { name: "打开 README.md" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新建文件" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新建文件夹" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "编辑 README.md" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "下载 README.md" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开 README.md" }));

  expect(screen.queryByText("Markdown Title")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "在编辑器中打开" })).not.toBeInTheDocument();
});

test("read-only file permission allows preview but hides write actions", async () => {
  const user = userEvent.setup();
  const writeFile = vi.fn();
  const deletePath = vi.fn();
  const client = createClient({ writeFile, deletePath });

  render(<FilesScreen botAlias="main" client={client} canWriteFiles={false} canOpenSystemFolder />);

  expect(await screen.findByRole("button", { name: "打开 README.md" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新建文件" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新建文件夹" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "在系统文件夹中打开" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "编辑 README.md" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重命名 README.md" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "删除 README.md" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开 README.md" }));

  expect(await screen.findByRole("heading", { name: "Markdown Title" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "全文读取" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "下载" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "在编辑器中打开" })).not.toBeInTheDocument();
  expect(writeFile).not.toHaveBeenCalled();
  expect(deletePath).not.toHaveBeenCalled();
});

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    login: async (): Promise<SessionState> => ({
      currentBotAlias: "main",
      currentPath: "C:\\workspace",
      isLoggedIn: true,
      username: "demo",
      role: "member",
      capabilities: ["terminal_exec", "admin_ops"],
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
    openBotWorkdir: async () => ({
      opened: true,
      path: "C:\\workspace",
      platform: "windows",
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
            "![Remote Chart](https://example.com/chart.png)",
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
    getGitProxySettings: async () => ({ address: "", port: "" }),
    updateGitProxySettings: async () => ({ address: "", port: "" }),
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
  const code = screen.getByText("const answer = 42;");
  expect(code).toBeInTheDocument();
  expect(code.closest(".group")).toHaveClass("border", "border-[var(--code-border)]", "bg-[var(--code-bg)]");
  expect(screen.getByRole("button", { name: "复制代码块" })).toHaveClass(
    "border-[var(--code-copy-border)]",
    "bg-[var(--code-copy-bg)]",
    "text-[var(--code-copy-text)]",
  );
});

test("markdown code block copy falls back to execCommand", async () => {
  const user = userEvent.setup();
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: vi.fn(() => true),
  });
  const execCommand = vi.spyOn(document, "execCommand");
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(globalThis.navigator, "clipboard", {
    configurable: true,
    value: undefined,
  });

  render(<FilesScreen botAlias="main" client={createClient()} />);
  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  await user.click(await screen.findByRole("button", { name: "复制代码块" }));

  expect(execCommand).toHaveBeenCalledWith("copy");
  expect(await screen.findByRole("button", { name: "已复制代码块" })).toBeInTheDocument();
});










test("passes detected file encoding when saving from editor", async () => {
  vi.unstubAllGlobals();
  const user = userEvent.setup();
  const writeSpy = vi.fn(async () => ({
    path: "notes.txt",
    fileSizeBytes: 12,
    lastModifiedNs: "1776420510390927701",
    encoding: "gb18030",
  }));
  const client = createClient({
    readFileFull: async () => ({
      content: "旧内容",
      mode: "cat",
      fileSizeBytes: 8,
      isFullContent: true,
      lastModifiedNs: "1776420510390927700",
      encoding: "gb18030",
    }),
    writeFile: writeSpy,
  });

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "编辑 notes.txt" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" });
  await user.clear(editor);
  await user.type(editor, "新内容");
  await user.click(screen.getByRole("button", { name: "保存" }));

  expect(writeSpy).toHaveBeenCalledWith(
    "main",
    "notes.txt",
    "新内容",
    "1776420510390927700",
    "gb18030",
  );
});







