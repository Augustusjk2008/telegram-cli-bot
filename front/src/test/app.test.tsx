import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../app/App";
import type { ChatMessage } from "../services/types";
import { MockWebBotClient } from "../services/mockWebBotClient";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

test("renders standalone login screen without backend", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Web Bot" })).toBeInTheDocument();
  expect(screen.getByLabelText("访问口令")).toBeInTheDocument();
});

test("shows bottom navigation after entering demo app shell", async () => {
  render(<App />);
  await userEvent.type(screen.getByLabelText("访问口令"), "123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "文件" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Git" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "设置" })).toBeInTheDocument();
  expect(sessionStorage.getItem("web-api-token")).toBe("123");
  expect(localStorage.getItem("web-api-token")).toBeNull();
});

test("re-login after tab close restores the last selected bot", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));
  expect(localStorage.getItem("web-current-bot")).toBe("team2");

  unmount();
  sessionStorage.clear();

  render(<App />);
  expect(screen.getByLabelText("访问口令")).toBeInTheDocument();

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByRole("button", { name: "team2" })).toBeInTheDocument();
});

test("keeps the waiting state after switching bots away and back", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "sendMessage").mockImplementation(
    async (_botAlias: string, _text: string, _onChunk: (chunk: string) => void): Promise<ChatMessage> =>
      new Promise((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-later",
            role: "assistant",
            text: "完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 3500);
      }),
  );

  render(<App />);
  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("已等待 1 秒", {}, { timeout: 2500 })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));

  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 1100));
  });

  await user.click(screen.getByRole("button", { name: "team2" }));
  await user.click(await screen.findByRole("button", { name: /main/i }));

  expect(await screen.findByText(/已等待 [1-9]\d* 秒/, {}, { timeout: 1500 })).toBeInTheDocument();
}, 10000);

test("settings tab shows cli params and tunnel status", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));

  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
  expect(screen.getByLabelText("推理努力程度")).toBeInTheDocument();
  expect(screen.getByText("公网访问")).toBeInTheDocument();
  expect(screen.getByText("https://demo.trycloudflare.com")).toBeInTheDocument();
});

test("settings tab can save cli params and restart tunnel", async () => {
  const user = userEvent.setup();
  const updateSpy = vi.spyOn(MockWebBotClient.prototype, "updateCliParam");
  const restartSpy = vi.spyOn(MockWebBotClient.prototype, "restartTunnel");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));
  await screen.findByLabelText("推理努力程度");

  await user.selectOptions(screen.getByLabelText("推理努力程度"), "high");
  await user.click(screen.getByRole("button", { name: "保存 推理努力程度" }));
  expect(updateSpy).toHaveBeenCalledWith("main", "reasoning_effort", "high");
  expect(await screen.findByText("参数已保存")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重启 Tunnel" }));
  expect(restartSpy).toHaveBeenCalledTimes(1);
});

test("settings tab can update bot working directory", async () => {
  const user = userEvent.setup();
  const workdirSpy = vi.spyOn(MockWebBotClient.prototype, "updateBotWorkdir");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));
  const input = await screen.findByLabelText("工作目录");
  await user.clear(input);
  await user.type(input, "C:\\workspace\\updated");
  await user.click(screen.getByRole("button", { name: "保存工作目录" }));

  expect(workdirSpy).toHaveBeenCalledWith("main", "C:\\workspace\\updated");
  expect(await screen.findByText("工作目录已更新")).toBeInTheDocument();
});

test("opening bot switcher refreshes bot status and shows busy", async () => {
  const user = userEvent.setup();
  const listBotsSpy = vi.spyOn(MockWebBotClient.prototype, "listBots")
    .mockResolvedValueOnce([
      {
        alias: "main",
        cliType: "kimi",
        status: "running",
        workingDir: "C:\\workspace\\demo",
        lastActiveText: "运行中",
      },
      {
        alias: "team2",
        cliType: "claude",
        status: "running",
        workingDir: "C:\\workspace\\plans",
        lastActiveText: "运行中",
      },
    ])
    .mockResolvedValueOnce([
      {
        alias: "main",
        cliType: "kimi",
        status: "busy",
        workingDir: "C:\\workspace\\demo",
        lastActiveText: "处理中",
      },
      {
        alias: "team2",
        cliType: "claude",
        status: "running",
        workingDir: "C:\\workspace\\plans",
        lastActiveText: "运行中",
      },
    ]);

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));

  expect(listBotsSpy).toHaveBeenCalledTimes(2);
  expect(await screen.findByText("处理中")).toBeInTheDocument();
  expect(screen.getByText("kimi: C:\\workspace\\demo")).toBeInTheDocument();
});

test("marks a bot unread after a hidden reply completes and clears it on return", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "sendMessage").mockImplementation(
    async (_botAlias: string, _text: string, _onChunk: (chunk: string) => void): Promise<ChatMessage> =>
      new Promise((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-hidden",
            role: "assistant",
            text: "后台完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 800);
      }),
  );

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.type(screen.getByPlaceholderText("输入消息"), "继续处理");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));

  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  });

  await user.click(screen.getByRole("button", { name: "team2" }));
  expect(await screen.findByText("未读")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /main/i }));
  expect(await screen.findByText("后台完成")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "main" }));
  expect(screen.queryByText("未读")).not.toBeInTheDocument();
});

test("main bot settings can restart service and rebuild frontend with live logs", async () => {
  const user = userEvent.setup();
  const restartServiceSpy = vi.spyOn(MockWebBotClient.prototype, "restartService");
  const runScriptStreamSpy = vi.spyOn(MockWebBotClient.prototype, "runSystemScriptStream").mockImplementation(
    async (scriptName: string, onLog: (line: string) => void) => {
      onLog("npm run build");
      await Promise.resolve();
      onLog("vite build finished");
      return {
        scriptName,
        success: true,
        output: "vite build finished",
      };
    },
  );

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));

  await user.click(await screen.findByRole("button", { name: "重建前端" }));
  expect(runScriptStreamSpy).toHaveBeenCalledWith("build_web_frontend", expect.any(Function));
  const buildDialog = await screen.findByRole("dialog", { name: "前端构建日志" });
  expect(buildDialog).toHaveTextContent("npm run build");
  expect(buildDialog).toHaveTextContent("vite build finished");
  expect(await screen.findByText("前端构建成功")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重启服务" }));
  expect(restartServiceSpy).toHaveBeenCalledTimes(1);
  expect(await screen.findByText(/已请求重启服务/)).toBeInTheDocument();
});

test("immersive chat mode hides outer chrome but keeps the composer visible", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "进入沉浸模式" }));

  expect(screen.queryByRole("button", { name: "main" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "文件" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重置会话" })).not.toBeInTheDocument();
  expect(screen.getByPlaceholderText("输入消息")).toBeInTheDocument();
});
