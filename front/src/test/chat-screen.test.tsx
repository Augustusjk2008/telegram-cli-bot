import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import type { ChatMessage, GitActionResult, GitDiffPayload, GitOverview, SystemScript } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  const baseClient: WebBotClient = {
    login: async () => ({
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      canExec: true,
      canAdmin: true,
    }),
    listBots: async () => [],
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
    }),
    listMessages: async () => [],
    sendMessage: async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("Mock response");
      return {
        id: "assistant-1",
        role: "assistant",
        text: "Mock response",
        createdAt: new Date().toISOString(),
        state: "done",
      };
    },
    getCurrentPath: async () => "C:\\workspace",
      listFiles: async () => ({
        workingDir: "C:\\workspace",
        entries: [],
      }),
      changeDirectory: async () => "C:\\workspace",
      createDirectory: async () => undefined,
      deletePath: async () => undefined,
      readFile: async () => "",
      readFileFull: async () => "",
      uploadFile: async () => undefined,
    downloadFile: async () => undefined,
    resetSession: async () => undefined,
    killTask: async () => undefined,
    restartService: async () => undefined,
    getGitProxySettings: async () => ({ port: "" }),
    updateGitProxySettings: async () => ({ port: "" }),
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
      path: "tracked.txt",
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
    updateBotWorkdir: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      lastActiveText: "运行中",
    }),
    getCliParams: async () => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    updateCliParam: async () => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    resetCliParams: async () => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    getTunnelStatus: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    startTunnel: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    stopTunnel: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    restartTunnel: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    listSystemScripts: async (): Promise<SystemScript[]> => [],
    runSystemScript: async () => ({
      scriptName: "demo",
      success: true,
      output: "ok",
    }),
    runSystemScriptStream: async () => ({
      scriptName: "demo",
      success: true,
      output: "ok",
    }),
  };
  return { ...baseClient, ...overrides };
}

afterEach(() => {
  vi.useRealTimers();
});

test("shows a user message after sending text", async () => {
  const client = createClient({
    sendMessage: async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("已收到");
      return {
        id: "assistant-immediate",
        role: "assistant",
        text: "已收到",
        elapsedSeconds: 3,
        createdAt: new Date().toISOString(),
        state: "done",
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "修一下这个 bug");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("修一下这个 bug")).toBeInTheDocument();
  expect(await screen.findByText("用时 3 秒")).toBeInTheDocument();
});

test("shows streaming state before assistant message completes", async () => {
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-later",
            role: "assistant",
            text: "稍后完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "继续");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(screen.getByText("正在输出...")).toBeInTheDocument();
  expect(await screen.findByText("稍后完成")).toBeInTheDocument();
});

test("shows a streaming placeholder before the first assistant chunk arrives", async () => {
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-final",
            role: "assistant",
            text: "# 最终结果\n- 已完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "继续");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("正在输出...")).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "最终结果" })).toBeInTheDocument();
});

test("renders loaded assistant history as markdown but keeps user and system text plain", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "# 用户消息",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "system-1",
        role: "system",
        text: "# 系统消息",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "# 助手结果\n- 第一项",
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("heading", { name: "助手结果" })).toBeInTheDocument();
  expect(screen.getByText("# 用户消息")).toBeInTheDocument();
  expect(screen.getByText("# 系统消息")).toBeInTheDocument();
});

test("kill button is disabled while idle and highlighted while streaming", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-later",
            role: "assistant",
            text: "稍后完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} isVisible />);

  const killButton = await screen.findByRole("button", { name: "终止任务" });
  expect(killButton).toBeDisabled();

  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByRole("button", { name: "终止任务" })).toBeEnabled();
});

test("switching bots resets chat history instead of mixing conversations", async () => {
  const client = createClient({
    listMessages: async (botAlias: string): Promise<ChatMessage[]> => {
      if (botAlias === "main") {
        return [{
          id: "main-1",
          role: "assistant",
          text: "main-history",
          createdAt: new Date().toISOString(),
          state: "done",
        }];
      }
      return [{
        id: "team2-1",
        role: "assistant",
        text: "team2-history",
        createdAt: new Date().toISOString(),
        state: "done",
      }];
    },
  });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("main-history")).toBeInTheDocument();

  rerender(<ChatScreen botAlias="team2" client={client} />);

  expect(await screen.findByText("team2-history")).toBeInTheDocument();
  expect(screen.queryByText("main-history")).not.toBeInTheDocument();
});

test("scrolls to the latest message on first load and when shown again", async () => {
  const original = HTMLElement.prototype.scrollIntoView;
  const scrollSpy = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollSpy,
  });

  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "latest",
      createdAt: new Date().toISOString(),
      state: "done",
    }],
  });

  try {
    const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
    expect(await screen.findByText("latest")).toBeInTheDocument();
    expect(scrollSpy).toHaveBeenCalled();

    scrollSpy.mockClear();

    rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
    rerender(<ChatScreen botAlias="main" client={client} isVisible />);

    expect(scrollSpy).toHaveBeenCalled();
  } finally {
    if (original) {
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
        configurable: true,
        value: original,
      });
    } else {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  }
});

test("shows waiting time while a reply is still pending", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          onChunk("done");
          resolve({
            id: "assistant-done",
            role: "assistant",
            text: "done",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 1600);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("已等待 1 秒", {}, { timeout: 2500 })).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByTestId("assistant-markdown-message")).toHaveTextContent("done");
  }, { timeout: 3000 });
}, 8000);

test("keeps showing a visible streaming badge while preview text is updating", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void, onStatus) =>
      new Promise<ChatMessage>((resolve) => {
        onStatus?.({ previewText: "正在整理上下文" });
        window.setTimeout(() => {
          resolve({
            id: "assistant-done",
            role: "assistant",
            text: "完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("正在整理上下文")).toBeInTheDocument();
  expect(screen.getByText("正在输出")).toBeInTheDocument();
});

test("shows reset kill and system-script actions for main bot", async () => {
  const client = createClient({
    listSystemScripts: async () => [{
      scriptName: "network_traffic",
      displayName: "网络流量",
      description: "查看网络状态",
      path: "C:\\scripts\\network_traffic.ps1",
    }],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("button", { name: "系统脚本" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重置会话" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "终止任务" })).toBeInTheDocument();
});

test("does not force-scroll to the bottom once the user scrolls away during streaming", async () => {
  const user = userEvent.setup();
  const original = HTMLElement.prototype.scrollIntoView;
  const scrollSpy = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollSpy,
  });

  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void, onStatus) =>
      new Promise<ChatMessage>((resolve) => {
        onStatus?.({ previewText: "第一段预览" });
        window.setTimeout(() => {
          onStatus?.({ previewText: "第二段预览" });
        }, 80);
        window.setTimeout(() => {
          resolve({
            id: "assistant-final",
            role: "assistant",
            text: "最终结果",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 160);
      }),
  });

  let scrollTop = 1500;

  try {
    render(<ChatScreen botAlias="main" client={client} />);
    expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    Object.defineProperties(scrollContainer, {
      scrollHeight: {
        configurable: true,
        get: () => 2200,
      },
      clientHeight: {
        configurable: true,
        get: () => 600,
      },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
      },
    });

    await user.type(screen.getByPlaceholderText("输入消息"), "继续");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("第一段预览")).toBeInTheDocument();

    scrollSpy.mockClear();
    scrollTop = 400;
    fireEvent.scroll(scrollContainer);

    expect(await screen.findByText("最终结果")).toBeInTheDocument();
    expect(scrollSpy).not.toHaveBeenCalled();
  } finally {
    if (original) {
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
        configurable: true,
        value: original,
      });
    } else {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  }
}, 10000);

test("shows compact system script titles without verbose metadata", async () => {
  const user = userEvent.setup();
  const client = createClient({
    listSystemScripts: async () => [{
      scriptName: "network_traffic",
      displayName: "网络流量。查看当前网络流量与连接状态。",
      description: "查看网络状态并输出详细路径",
      path: "C:\\scripts\\network_traffic.ps1",
    }],
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "系统脚本" }));

  expect(await screen.findByRole("button", { name: "网络流量" })).toBeInTheDocument();
  expect(screen.queryByText("查看网络状态并输出详细路径")).not.toBeInTheDocument();
  expect(screen.queryByText("C:\\scripts\\network_traffic.ps1")).not.toBeInTheDocument();
});

test("opens a file preview dialog when clicking a local markdown file link", async () => {
  const user = userEvent.setup();
  const readSpy = vi.fn(async () => "# README\n\n文件预览");
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "[查看 README](C:/workspace/README.md)",
      createdAt: new Date().toISOString(),
      state: "done",
    }],
    readFile: readSpy,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("link", { name: "查看 README" }));

  expect(readSpy).toHaveBeenCalledWith("main", "README.md");
  expect(await screen.findByRole("dialog", { name: "README.md" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "README" })).toBeInTheDocument();
});

test("opens a file preview dialog when clicking a local absolute file link outside the working dir", async () => {
  const user = userEvent.setup();
  const readSpy = vi.fn(async () => "外部文件预览");
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "[查看日志](C:/logs/app.log)",
      createdAt: new Date().toISOString(),
      state: "done",
    }],
    readFile: readSpy,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("link", { name: "查看日志" }));

  expect(readSpy).toHaveBeenCalledWith("main", "C:/logs/app.log");
  expect(await screen.findByRole("dialog", { name: "C:/logs/app.log" })).toBeInTheDocument();
});

test("restores in-progress reply after reopening and refreshes to final history", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  let historyCalls = 0;
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => {
      historyCalls += 1;
      if (historyCalls === 1) {
        return [{
          id: "user-1",
          role: "user",
          text: "继续执行",
          createdAt: new Date().toISOString(),
          state: "done",
        }];
      }
      return [
        {
          id: "user-1",
          role: "user",
          text: "继续执行",
          createdAt: new Date().toISOString(),
          state: "done",
        },
        {
          id: "assistant-final",
          role: "assistant",
          text: "最终结果",
          createdAt: new Date().toISOString(),
          state: "done",
        },
      ];
    },
    getBotOverview: async () => {
      overviewCalls += 1;
      if (overviewCalls === 1) {
        return {
          alias: "main",
          cliType: "codex",
          status: "busy",
          workingDir: "C:\\workspace",
          isProcessing: true,
          runningReply: {
            previewText: "处理中预览",
            startedAt: "2026-04-09T10:40:00",
            updatedAt: "2026-04-09T10:40:05",
          },
        };
      }
      return {
        alias: "main",
        cliType: "codex",
        status: "running",
        workingDir: "C:\\workspace",
        isProcessing: false,
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  expect(screen.getByText("处理中预览")).toBeInTheDocument();
  expect(screen.getByText(/正在生成|处理中预览/)).toBeInTheDocument();

  await act(async () => {
    vi.advanceTimersByTime(1100);
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(screen.getByText("最终结果")).toBeInTheDocument();
}, 8000);

test("shows the last unfinished preview after a restored session is no longer running", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "user-1",
      role: "user",
      text: "继续执行",
      createdAt: new Date().toISOString(),
      state: "done",
    }],
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      runningReply: {
        userText: "继续执行",
        previewText: "恢复到上次预览",
        startedAt: "2026-04-09T10:40:00",
        updatedAt: "2026-04-09T10:40:05",
      },
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("恢复到上次预览")).toBeInTheDocument();
  expect(screen.getByText("检测到上次未完成任务，已恢复最近预览。")).toBeInTheDocument();
});

test("shows persisted elapsed badge from loaded history", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "历史结果",
      createdAt: new Date().toISOString(),
      elapsedSeconds: 8,
      state: "done",
    }],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("历史结果")).toBeInTheDocument();
  expect(screen.getByText("用时 8 秒")).toBeInTheDocument();
});
