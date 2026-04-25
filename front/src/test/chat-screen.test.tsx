import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ChatMessage, ChatTraceDetails, CliParamsPayload, GitActionResult, GitDiffPayload, GitOverview, SystemScript } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function modelCliParams(model: string): CliParamsPayload {
  return {
    cliType: "codex",
    params: { model },
    defaults: { model: "gpt-5.4" },
    schema: {
      model: {
        type: "string",
        description: "模型选择",
        enum: ["gpt-5.5", "gpt-5.4"],
      },
    },
  };
}

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
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
    getMessageTrace: async (): Promise<ChatTraceDetails> => ({
      traceCount: 0,
      toolCallCount: 0,
      processCount: 0,
      trace: [],
    }),
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
    readFile: async () => ({
      content: "",
      mode: "head" as const,
      fileSizeBytes: 0,
      isFullContent: true,
    }),
    readFileFull: async () => ({
      content: "",
      mode: "cat" as const,
      fileSizeBytes: 0,
      isFullContent: true,
    }),
    uploadFile: async () => undefined,
    downloadFile: async () => undefined,
    resetSession: async () => undefined,
    killTask: async () => "已发送终止任务请求",
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
    ...overrides,
  });
}

afterEach(() => {
  vi.useRealTimers();
});

test("shows model selector in chat action bar and saves selected model", async () => {
  const updateCliParam = vi.fn(async (_botAlias: string, _key: string, value: unknown) => modelCliParams(String(value)));
  const user = userEvent.setup();
  const client = createClient({
    getCliParams: async () => modelCliParams("gpt-5.5"),
    updateCliParam,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const selector = await screen.findByLabelText("模型");
  expect(selector).toHaveValue("gpt-5.5");

  await user.selectOptions(selector, "gpt-5.4");

  expect(updateCliParam).toHaveBeenCalledWith("main", "model", "gpt-5.4", "codex");
  expect(selector).toHaveValue("gpt-5.4");
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
  expect(screen.queryByText("用时 3 秒")).not.toBeInTheDocument();
});

test("uploads chat attachments and appends absolute paths to the sent message", async () => {
  const user = userEvent.setup();
  const sendSpy = vi.fn(
    async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("已收到");
      return {
        id: "assistant-attachment",
        role: "assistant" as const,
        text: "已收到",
        createdAt: new Date().toISOString(),
        state: "done" as const,
      };
    },
  );
  const uploadChatAttachment = vi.fn(async (_botAlias: string, file: File) => ({
    filename: file.name,
    savedPath: `C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\${file.name}`,
    size: file.size,
  }));
  const client = createClient({
    sendMessage: sendSpy as never,
    uploadChatAttachment: uploadChatAttachment as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  const attachmentInput = screen.getByTestId("chat-attachment-input");
  const file = new File(["hello"], "report.txt", { type: "text/plain" });
  await user.upload(attachmentInput, file);

  await waitFor(() => {
    expect(uploadChatAttachment).toHaveBeenCalledTimes(1);
  });
  expect(await screen.findByRole("button", { name: "移除附件 report.txt" })).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "请分析这个附件");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => {
    expect(sendSpy).toHaveBeenCalledWith(
      "main",
      "请分析这个附件\n\n附件路径为：C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });

  expect(await screen.findByText("report.txt")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "删除附件文件 report.txt" })).toBeInTheDocument();
  expect(screen.queryByText((content) => (
    content.includes("附件路径为：")
    && content.includes("report.txt")
  ))).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "移除附件 report.txt" })).not.toBeInTheDocument();
});

test("deletes attachment files from user message pills without exposing injected prompt text", async () => {
  const user = userEvent.setup();
  const deleteSpy = vi.fn(async (_botAlias: string, savedPath: string) => ({
    filename: "report.txt",
    savedPath,
    existed: true,
    deleted: true,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-attachment-1",
        role: "user",
        text: "请参考附件\n\n附件路径为：C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ],
    deleteChatAttachment: deleteSpy as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("请参考附件")).toBeInTheDocument();
  expect(await screen.findByText("report.txt")).toBeInTheDocument();
  expect(screen.queryByText((content) => content.includes("附件路径为："))).not.toBeInTheDocument();

  await user.click(await screen.findByRole("button", { name: "删除附件文件 report.txt" }));

  await waitFor(() => {
    expect(deleteSpy).toHaveBeenCalledWith(
      "main",
      "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
    );
  });
  expect(await screen.findByText("已删除")).toBeInTheDocument();
});

test("submits the chat composer when pressing Shift+Enter", async () => {
  const sendSpy = vi.fn(
    async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("已通过快捷键发送");
      return {
        id: "assistant-shift-enter",
        role: "assistant" as const,
        text: "已通过快捷键发送",
        createdAt: new Date().toISOString(),
        state: "done" as const,
      };
    },
  );
  const client = createClient({
    sendMessage: sendSpy,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  const composer = await screen.findByPlaceholderText("输入消息");
  fireEvent.change(composer, { target: { value: "Shift+Enter 发送" } });
  fireEvent.keyDown(composer, { key: "Enter", code: "Enter", shiftKey: true });

  await waitFor(() => {
    expect(sendSpy).toHaveBeenCalledWith(
      "main",
      "Shift+Enter 发送",
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });

  expect(await screen.findByText("Shift+Enter 发送")).toBeInTheDocument();
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

test("treats inactive history streaming rows as completed", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      historyCount: 2,
    }),
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-22T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "最终回答",
        createdAt: "2026-04-22T10:00:01",
        state: "streaming",
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("最终回答")).toBeInTheDocument();
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
  expect(screen.queryByText("正在输出...")).not.toBeInTheDocument();
});

test("keeps history streaming rows active while overview is processing", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "busy",
      workingDir: "C:\\workspace",
      isProcessing: true,
      historyCount: 2,
    }),
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-22T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "处理中预览",
        createdAt: "2026-04-22T10:00:01",
        state: "streaming",
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("处理中预览")).toBeInTheDocument();
  expect(screen.getByText("正在输出")).toBeInTheDocument();
});

test("renders empty tool call payloads with readable fallback instead of raw empty json", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: async (
      _botAlias: string,
      _text: string,
      _onChunk: (chunk: string) => void,
      _onStatus,
      onTrace,
    ) => {
      onTrace?.({
        kind: "tool_call",
        title: "list_mcp_resources",
        toolName: "list_mcp_resources",
        callId: "call_empty",
        summary: "{}",
        payload: {
          arguments: {},
          raw_arguments: "{}",
        },
      } as never);
      onTrace?.({
        kind: "tool_result",
        callId: "call_empty",
        summary: "{}",
        payload: {
          output: {},
        },
      } as never);
      return {
        id: "assistant-empty-tool",
        role: "assistant",
        text: "已经检查完资源列表。",
        createdAt: new Date().toISOString(),
        state: "done",
      } as ChatMessage;
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "看下资源");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("已经检查完资源列表。")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "展开过程详情" }));

  expect(screen.getByText("无参数")).toBeInTheDocument();
  expect(screen.getByText("已返回，无可显示内容")).toBeInTheDocument();
  expect(screen.queryByText("{}")).not.toBeInTheDocument();
});

test("lazy-loads trace details and groups tool call/result into one trace card", async () => {
  const user = userEvent.setup();
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      {
        kind: "commentary",
        summary: "我先检查目录结构。",
      },
      {
        kind: "tool_call",
        title: "shell_command",
        toolName: "shell_command",
        callId: "call_1",
        summary: "Get-Content -Path todo.txt",
        payload: {
          arguments: {
            command: "Get-Content -Path todo.txt",
          },
        },
      },
      {
        kind: "tool_result",
        callId: "call_1",
        summary: "Exit code: 1\nWall time: 1.3 seconds\nOutput:\nboom",
        payload: {
          output: "Exit code: 1\nWall time: 1.3 seconds\nOutput:\nboom",
        },
      },
      {
        kind: "commentary",
        summary: "目录已读取完成。",
      },
    ],
    traceCount: 4,
    toolCallCount: 1,
    processCount: 2,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "列出当前目录",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "目录已读取完成。",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          traceCount: 4,
          toolCallCount: 1,
          processCount: 2,
        },
      },
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("目录已读取完成。")).toBeInTheDocument();
  expect(getMessageTrace).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "展开过程详情" }));

  expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-1");
  expect(await screen.findByText("我先检查目录结构。")).toBeInTheDocument();
  expect(screen.getByText("工具调用 1")).toBeInTheDocument();
  expect(screen.getByText("Get-Content -Path todo.txt")).toBeInTheDocument();
  expect(screen.getByText("返回")).toBeInTheDocument();
  expect(screen.getByText("Exit 1")).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes("Wall time: 1.3 seconds") && content.includes("Output:"))).toBeInTheDocument();

  const panel = screen.getByTestId("chat-trace-panel-assistant-1");
  const traceItems = Array.from(panel.querySelectorAll("[data-trace-seq]"));
  expect(traceItems).toHaveLength(3);
  expect(traceItems[0]?.textContent).toContain("我先检查目录结构。");
  expect(traceItems[1]?.textContent).toContain("工具调用 1");
  expect(traceItems[1]?.textContent).toContain("Exit 1");
  expect(traceItems[2]?.textContent).toContain("目录已读取完成。");
});

test("shows pending tool state when tool call has no matching result", async () => {
  const user = userEvent.setup();
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      {
        kind: "tool_call",
        title: "shell_command",
        toolName: "shell_command",
        callId: "call_pending",
        summary: "Get-ChildItem -Force",
        payload: {
          arguments: {
            command: "Get-ChildItem -Force",
          },
        },
      },
    ],
    traceCount: 1,
    toolCallCount: 1,
    processCount: 0,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "列出当前目录",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "目录已读取完成。",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          traceCount: 1,
          toolCallCount: 1,
          processCount: 0,
        },
      },
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "展开过程详情" }));

  expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-1");
  expect(await screen.findByText("等待返回")).toBeInTheDocument();
  expect(screen.getByText(/尚无返回/)).toBeInTheDocument();
  expect(screen.getByText("Get-ChildItem -Force")).toBeInTheDocument();
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

test("recovers from a stalled sse completion by syncing finished history", async () => {
  vi.useFakeTimers();
  const getBotOverview = vi.fn(async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
    }));
  const listMessages = vi
    .fn<() => Promise<ChatMessage[]>>()
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([
      {
        id: "user-server-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-20T12:00:00",
        state: "done",
      },
      {
        id: "assistant-server-1",
        role: "assistant",
        text: "最终结果",
        createdAt: "2026-04-20T12:00:01",
        state: "done",
      },
    ]);
  const client = createClient({
    getBotOverview: getBotOverview as never,
    listMessages: listMessages as never,
    sendMessage: (_botAlias: string, _text: string, onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>(() => {
        window.setTimeout(() => {
          onChunk("最终结果");
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(screen.getByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "继续" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1300);
  });

  expect(screen.getByText("最终结果")).toBeInTheDocument();
  expect(screen.getByText(/已等待 \d+ 秒/)).toBeInTheDocument();
  expect(screen.getByText("正在输出")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2600);
    await Promise.resolve();
  });

  expect(getBotOverview).toHaveBeenCalledTimes(2);
  expect(listMessages).toHaveBeenCalledTimes(2);
  expect(screen.getByText("最终结果")).toBeInTheDocument();
  expect(screen.queryByText(/已等待 \d+ 秒/)).not.toBeInTheDocument();
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
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

test("assistant send does not let an old idle poll replace the finishing reply with a stale streaming row", async () => {
  vi.useFakeTimers();
  let overviewCalls = 0;
  const listMessages = vi
    .fn<() => Promise<ChatMessage[]>>()
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([
      {
        id: "user-server-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-20T12:00:00",
        state: "done",
      },
      {
        id: "assistant-server-1",
        role: "assistant",
        text: "轮询中的旧预览",
        createdAt: "2026-04-20T12:00:01",
        state: "streaming",
      },
    ]);
  const client = createClient({
    getBotOverview: async () => {
      overviewCalls += 1;
      return {
        alias: "assistant1",
        cliType: "codex",
        status: overviewCalls === 1 ? "running" : "busy",
        workingDir: "C:\\workspace",
        botMode: "assistant",
        isProcessing: overviewCalls > 1,
      };
    },
    listMessages: listMessages as never,
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-done",
            role: "assistant",
            text: "真正完成的回复",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 6000);
      }),
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(screen.getByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "继续" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5100);
  });

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });

  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByText("真正完成的回复")).toBeInTheDocument();
  expect(screen.queryByText("轮询中的旧预览")).not.toBeInTheDocument();
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
  expect(screen.queryByText(/已等待 \d+ 秒/)).not.toBeInTheDocument();
});

test("shows reset kill and system-function actions for non-main bots", async () => {
  const client = createClient({
    listSystemScripts: async () => [{
      scriptName: "network_traffic.ps1",
      displayName: "网络流量",
      description: "查看网络状态",
      path: "C:\\workspace\\team2\\scripts\\network_traffic.ps1",
    }],
  });

  render(<ChatScreen botAlias="team2" client={client} />);

  expect(await screen.findByRole("button", { name: "系统功能" })).toBeInTheDocument();
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

test("scrolls back to the bottom when a hidden chat screen becomes visible again", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-1",
        role: "assistant",
        text: "第一条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-2",
        role: "assistant",
        text: "第二条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ],
  });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
  expect(await screen.findByText("第二条")).toBeInTheDocument();

  const scrollContainer = screen.getByTestId("chat-scroll-container");
  let scrollTop = 0;
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
      set: (value: number) => {
        scrollTop = value;
      },
    },
  });

  scrollTop = 100;
  fireEvent.scroll(scrollContainer);

  rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  rerender(<ChatScreen botAlias="main" client={client} isVisible />);

  await waitFor(() => {
    expect(scrollTop).toBe(2200);
  });
});

test("keeps a newly visible chat screen pinned when rendered content grows", async () => {
  const originalResizeObserver = window.ResizeObserver;
  let resizeCallback: ResizeObserverCallback | null = null;
  class MockResizeObserver {
    observe = vi.fn();
    disconnect = vi.fn();

    constructor(callback: ResizeObserverCallback) {
      resizeCallback = callback;
    }
  }
  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    value: MockResizeObserver,
  });

  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-1",
        role: "assistant",
        text: "第一条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-2",
        role: "assistant",
        text: "第二条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ],
  });

  try {
    const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
    expect(await screen.findByText("第二条")).toBeInTheDocument();

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    let scrollHeight = 1200;
    let scrollTop = 0;
    Object.defineProperties(scrollContainer, {
      scrollHeight: {
        configurable: true,
        get: () => scrollHeight,
      },
      clientHeight: {
        configurable: true,
        get: () => 600,
      },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = value;
        },
      },
    });

    rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
    rerender(<ChatScreen botAlias="main" client={client} isVisible />);

    await waitFor(() => {
      expect(scrollTop).toBe(1200);
    });

    scrollHeight = 2200;
    resizeCallback?.([] as unknown as ResizeObserverEntry[], {} as ResizeObserver);

    expect(scrollTop).toBe(2200);
  } finally {
    if (originalResizeObserver) {
      Object.defineProperty(window, "ResizeObserver", {
        configurable: true,
        value: originalResizeObserver,
      });
    } else {
      delete (window as { ResizeObserver?: unknown }).ResizeObserver;
    }
  }
});

test("opens system functions with bot-scoped calls and compact titles", async () => {
  const user = userEvent.setup();
  const listSystemScripts = vi.fn(async () => [{
    scriptName: "network_traffic.ps1",
    displayName: "网络流量。查看当前网络流量与连接状态。",
    description: "查看网络状态并输出详细路径",
    path: "C:\\workspace\\team2\\scripts\\network_traffic.ps1",
  }]);
  const runSystemScript = vi.fn(async () => ({
    scriptName: "network_traffic.ps1",
    success: true,
    output: "执行成功",
  }));
  const client = createClient({
    listSystemScripts,
    runSystemScript,
  });

  render(<ChatScreen botAlias="team2" client={client} />);
  await user.click(await screen.findByRole("button", { name: "系统功能" }));

  expect(listSystemScripts).toHaveBeenCalledWith("team2");
  expect(screen.getByRole("heading", { name: "系统功能" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "网络流量" })).toBeInTheDocument();
  expect(screen.queryByText("查看网络状态并输出详细路径")).not.toBeInTheDocument();
  expect(screen.queryByText("C:\\workspace\\team2\\scripts\\network_traffic.ps1")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "网络流量" }));

  expect(runSystemScript).toHaveBeenCalledWith("team2", "network_traffic.ps1");
  expect(await screen.findByText(/系统功能：网络流量。查看当前网络流量与连接状态。/)).toBeInTheDocument();
});

test("opens a file preview dialog when clicking a local markdown file link", async () => {
  const user = userEvent.setup();
  const readSpy = vi.fn(async () => ({
    content: "# README\n\n文件预览",
    mode: "head" as const,
    fileSizeBytes: 128,
    isFullContent: true,
  }));
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
  const readSpy = vi.fn(async () => ({
    content: "外部文件预览",
    mode: "head" as const,
    fileSizeBytes: 128,
    isFullContent: true,
  }));
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

test("chat screen trusts the history streaming row instead of merging overview.runningReply", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "列出当前目录",
        createdAt: "2026-04-18T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "我先检查目录结构。",
        createdAt: "2026-04-18T10:00:01",
        state: "streaming",
      },
    ],
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "busy",
      workingDir: "C:\\workspace",
      isProcessing: true,
      runningReply: {
        userText: "列出当前目录",
        previewText: "这段预览不应再单独插入",
        startedAt: "2026-04-18T10:00:01",
        updatedAt: "2026-04-18T10:00:02",
      },
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("我先检查目录结构。")).toBeInTheDocument();
  expect(screen.queryByText("这段预览不应再单独插入")).not.toBeInTheDocument();
  expect(screen.getAllByText("列出当前目录")).toHaveLength(1);
});

test("chat screen does not render restored synthetic reply bubbles after refresh", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "继续执行",
        createdAt: "2026-04-18T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "恢复到上次可见输出",
        createdAt: "2026-04-18T10:00:01",
        state: "error",
      },
    ],
    getBotOverview: async () => {
      overviewCalls += 1;
      return {
        alias: "main",
        cliType: "codex",
        status: overviewCalls === 1 ? "busy" : "running",
        workingDir: "C:\\workspace",
        isProcessing: false,
        runningReply: {
          userText: "继续执行",
          previewText: "恢复到上次可见输出",
          startedAt: "2026-04-18T10:00:01",
          updatedAt: "2026-04-18T10:00:05",
        },
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  expect(screen.getByText("恢复到上次可见输出")).toBeInTheDocument();
  expect(screen.queryByText("检测到上次未完成任务，已恢复最近预览。")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "继续" })).not.toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });

  expect(screen.getAllByText("恢复到上次可见输出")).toHaveLength(1);
});

test("does not show elapsed badge from loaded history", async () => {
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
  expect(screen.queryByText("用时 8 秒")).not.toBeInTheDocument();
});

test("assistant chat polls while idle and picks up scheduled cron runs", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  let historyCalls = 0;
  const client = createClient({
    getBotOverview: async () => {
      overviewCalls += 1;
      if (overviewCalls < 3) {
        return {
          alias: "assistant1",
          cliType: "codex",
          status: "running",
          workingDir: "C:\\workspace",
          botMode: "assistant",
          isProcessing: false,
        };
      }
      return {
        alias: "assistant1",
        cliType: "codex",
        status: "busy",
        workingDir: "C:\\workspace",
        botMode: "assistant",
        isProcessing: true,
        runningReply: {
          userText: "定时检查邮箱",
          previewText: "正在读取最新邮件",
          startedAt: "2026-04-16T18:00:00",
          updatedAt: "2026-04-16T18:00:02",
        },
      };
    },
    listMessages: async (): Promise<ChatMessage[]> => {
      historyCalls += 1;
      if (historyCalls < 2) {
        return [];
      }
      return [
        {
          id: "user-cron-1",
          role: "user",
          text: "定时检查邮箱",
          createdAt: "2026-04-16T18:00:00",
          state: "done",
        },
        {
          id: "assistant-cron-1",
          role: "assistant",
          text: "正在读取最新邮件",
          createdAt: "2026-04-16T18:00:01",
          state: "streaming",
        },
      ];
    },
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  expect(screen.queryByText("定时检查邮箱")).not.toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(10100);
  });

  expect(screen.getByText("定时检查邮箱")).toBeInTheDocument();
  expect(screen.getByText("正在读取最新邮件")).toBeInTheDocument();
});

test("hidden assistant chat does not start idle polling on mount", async () => {
  vi.useFakeTimers();

  const getBotOverview = vi.fn(async () => ({
    alias: "assistant1",
    cliType: "codex" as const,
    status: "running" as const,
    workingDir: "C:\\workspace",
    botMode: "assistant",
    isProcessing: false,
    historyCount: 0,
  }));
  const listMessages = vi.fn(async (): Promise<ChatMessage[]> => []);
  const client = createClient({
    getBotOverview,
    listMessages: listMessages as never,
  });

  render(<ChatScreen botAlias="assistant1" client={client} isVisible={false} />);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(getBotOverview).not.toHaveBeenCalled();
  expect(listMessages).not.toHaveBeenCalled();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });

  expect(getBotOverview).not.toHaveBeenCalled();
  expect(listMessages).not.toHaveBeenCalled();
});

test("hidden assistant chat activates when it becomes visible", async () => {
  const getBotOverview = vi.fn(async () => ({
    alias: "assistant1",
    cliType: "codex" as const,
    status: "running" as const,
    workingDir: "C:\\workspace",
    botMode: "assistant",
    isProcessing: false,
    historyCount: 0,
  }));
  const listMessages = vi.fn(async (): Promise<ChatMessage[]> => []);
  const client = createClient({
    getBotOverview,
    listMessages: listMessages as never,
  });

  const { rerender } = render(<ChatScreen botAlias="assistant1" client={client} isVisible={false} />);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(getBotOverview).not.toHaveBeenCalled();

  rerender(<ChatScreen botAlias="assistant1" client={client} isVisible />);

  await waitFor(() => {
    expect(getBotOverview).toHaveBeenCalledTimes(1);
    expect(listMessages).toHaveBeenCalledTimes(1);
  });
});

test("assistant idle polling requests history delta when history count changes", async () => {
  vi.useFakeTimers();
  const initialMessages: ChatMessage[] = [
    {
      id: "user-1",
      role: "user",
      text: "第一问",
      createdAt: "2026-04-16T18:00:00",
      state: "done",
    },
  ];
  const deltaMessages: ChatMessage[] = [
    {
      id: "assistant-2",
      role: "assistant",
      text: "增量回复",
      createdAt: "2026-04-16T18:00:02",
      state: "done",
    },
  ];
  let overviewCalls = 0;
  const getBotOverview = vi.fn(async () => {
    overviewCalls += 1;
    return {
      alias: "assistant1",
      cliType: "codex" as const,
      status: "running" as const,
      workingDir: "C:\\workspace",
      botMode: "assistant",
      isProcessing: false,
      historyCount: overviewCalls === 1 ? 1 : 2,
    };
  });
  const listMessages = vi.fn(async () => initialMessages);
  const listMessageDelta = vi.fn(async () => ({
    items: deltaMessages,
    reset: false,
  }));
  const client = createClient({
    getBotOverview,
    listMessages: listMessages as never,
  }) as WebBotClient & {
    listMessageDelta: typeof listMessageDelta;
  };
  client.listMessageDelta = listMessageDelta;

  render(<ChatScreen botAlias="assistant1" client={client} isVisible />);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(listMessages).toHaveBeenCalledTimes(1);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5100);
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(listMessageDelta).toHaveBeenCalledWith("assistant1", "user-1", 50);
  expect(screen.getByText("增量回复")).toBeInTheDocument();
});

test("assistant chat immediately shows manual cron prompts after the settings handoff event", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  let historyCalls = 0;
  const client = createClient({
    getBotOverview: async () => {
      overviewCalls += 1;
      if (overviewCalls === 1) {
        return {
          alias: "assistant1",
          cliType: "codex",
          status: "running",
          workingDir: "C:\\workspace",
          botMode: "assistant",
          isProcessing: false,
        };
      }
      return {
        alias: "assistant1",
        cliType: "codex",
        status: "busy",
        workingDir: "C:\\workspace",
        botMode: "assistant",
        isProcessing: true,
        runningReply: {
          userText: "检查最近邮件并总结重点",
          previewText: "正在读取最近邮件",
          startedAt: "2026-04-16T18:05:00",
          updatedAt: "2026-04-16T18:05:01",
        },
      };
    },
    listMessages: async (): Promise<ChatMessage[]> => {
      historyCalls += 1;
      if (historyCalls === 1) {
        return [];
      }
      return [
        {
          id: "user-cron-1",
          role: "user",
          text: "检查最近邮件并总结重点",
          createdAt: "2026-04-16T18:05:00",
          state: "done",
        },
        {
          id: "assistant-cron-1",
          role: "assistant",
          text: "正在读取最近邮件",
          createdAt: "2026-04-16T18:05:01",
          state: "streaming",
        },
      ];
    },
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  await act(async () => {
    window.dispatchEvent(new CustomEvent("assistant-cron-run-enqueued", {
      detail: {
        botAlias: "assistant1",
        runId: "run_123456",
        prompt: "检查最近邮件并总结重点",
        queuedAt: "2026-04-16T18:05:00",
      },
    }));
    await Promise.resolve();
  });

  expect(screen.getByText("检查最近邮件并总结重点")).toBeInTheDocument();
  expect(screen.getByText("正在输出...")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });

  expect(screen.getByText("正在读取最近邮件")).toBeInTheDocument();
});
