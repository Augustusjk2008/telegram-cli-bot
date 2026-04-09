import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import type { ChatMessage, SystemScript } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  return {
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
    readFile: async () => "",
    uploadFile: async () => undefined,
    downloadFile: async () => undefined,
    resetSession: async () => undefined,
    killTask: async () => undefined,
    listSystemScripts: async (): Promise<SystemScript[]> => [],
    runSystemScript: async () => ({
      scriptName: "demo",
      success: true,
      output: "ok",
    }),
    ...overrides,
  };
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
  expect(await screen.findByText(/正在生成/)).toBeInTheDocument();
  expect(await screen.findByText("稍后完成")).toBeInTheDocument();
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
  expect(await screen.findByText("done", {}, { timeout: 3000 })).toBeInTheDocument();
}, 8000);

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
