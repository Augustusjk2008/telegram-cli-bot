import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../app/App";
import type { ChatMessage } from "../services/types";
import { MockWebBotClient } from "../services/mockWebBotClient";

const terminalSessionMock = vi.hoisted(() => ({
  sendControl: vi.fn(),
  sendText: vi.fn(),
  fit: vi.fn(),
  focus: vi.fn(),
  dispose: vi.fn(),
  scrollToBottom: vi.fn(),
}));

vi.mock("../services/terminalSession", () => ({
  createTerminalSession: vi.fn((_container: HTMLElement, options: { onOpen?: () => void }) => ({
    term: {
      onWriteParsed: vi.fn(() => ({ dispose: vi.fn() })),
      onScroll: vi.fn(() => ({ dispose: vi.fn() })),
      scrollToBottom: terminalSessionMock.scrollToBottom,
      textarea: document.createElement("textarea"),
    },
    connect: vi.fn(() => options.onOpen?.()),
    dispose: terminalSessionMock.dispose,
    fit: terminalSessionMock.fit,
    focus: terminalSessionMock.focus,
    sendControl: terminalSessionMock.sendControl,
    sendText: terminalSessionMock.sendText,
  })),
}));

beforeEach(() => {
  terminalSessionMock.sendControl.mockReset();
  terminalSessionMock.sendText.mockReset();
  terminalSessionMock.fit.mockReset();
  terminalSessionMock.focus.mockReset();
  terminalSessionMock.dispose.mockReset();
  terminalSessionMock.scrollToBottom.mockReset();
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
  expect(screen.getByRole("heading", { name: "🦞Safe Claw" })).toBeInTheDocument();
  expect(screen.getByText("【志在空间 威震长空】")).toBeInTheDocument();
  expect(screen.getByText("2026")).toBeInTheDocument();
  expect(screen.getByLabelText("访问口令")).toBeInTheDocument();
  expect(document.title).toBe("🦞Safe Claw");
  expect(document.documentElement.dataset.theme).toBe("deep-space");
});

test("shows bottom navigation after entering demo app shell", async () => {
  render(<App />);
  await userEvent.type(screen.getByLabelText("访问口令"), "123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "文件" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "终端" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Git" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "设置" })).toBeInTheDocument();
  expect(sessionStorage.getItem("web-api-token")).toBe("123");
  expect(localStorage.getItem("web-api-token")).toBeNull();
});

test("initial login only mounts the active chat tab", async () => {
  const user = userEvent.setup();
  const getBotOverviewSpy = vi.spyOn(MockWebBotClient.prototype, "getBotOverview");
  const listFilesSpy = vi.spyOn(MockWebBotClient.prototype, "listFiles");
  const getGitOverviewSpy = vi.spyOn(MockWebBotClient.prototype, "getGitOverview");
  const getCliParamsSpy = vi.spyOn(MockWebBotClient.prototype, "getCliParams");
  const getTunnelStatusSpy = vi.spyOn(MockWebBotClient.prototype, "getTunnelStatus");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await act(async () => {
    await Promise.resolve();
  });

  expect(getBotOverviewSpy).toHaveBeenCalledTimes(1);
  expect(listFilesSpy).not.toHaveBeenCalled();
  expect(getGitOverviewSpy).not.toHaveBeenCalled();
  expect(getCliParamsSpy).not.toHaveBeenCalled();
  expect(getTunnelStatusSpy).not.toHaveBeenCalled();
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

  expect(await screen.findByText("界面主题")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "深空轨道" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "经典暖色" })).toBeInTheDocument();
  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
  expect(screen.getByLabelText("推理努力程度")).toBeInTheDocument();
  expect(screen.getByText("公网访问")).toBeInTheDocument();
  expect(screen.getByText("https://demo.trycloudflare.com")).toBeInTheDocument();
});

test("settings tab can switch and persist the global theme", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));
  await user.click(await screen.findByRole("button", { name: "经典暖色" }));

  expect(document.documentElement.dataset.theme).toBe("classic");
  expect(localStorage.getItem("web-ui-theme")).toBe("classic");
  expect(await screen.findByText("界面主题已切换")).toBeInTheDocument();
});

test("settings tab ignores optional tunnel failures and keeps core settings available", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "getTunnelStatus").mockRejectedValue(
    new Error("Unexpected token '<', \"<!doctype \"... is not valid JSON"),
  );

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));

  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
  expect(screen.getByLabelText("推理努力程度")).toBeInTheDocument();
  expect(screen.queryByText(/Unexpected token/)).not.toBeInTheDocument();
});

test("settings tab keeps existing load errors visible after theme switching", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "getBotOverview").mockRejectedValue(new Error("加载设置失败"));

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));
  expect((await screen.findAllByText("加载设置失败")).length).toBeGreaterThan(0);

  await user.click(screen.getByRole("button", { name: "经典暖色" }));

  expect(screen.queryAllByText("加载设置失败").length).toBeGreaterThan(0);
  expect(await screen.findByText("界面主题已切换")).toBeInTheDocument();
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

test("settings tab can update bot cli configuration", async () => {
  const user = userEvent.setup();
  const updateCliSpy = vi.spyOn(MockWebBotClient.prototype, "updateBotCli");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  expect(document.title).toBe("main - 🦞Safe Claw");

  await user.click(screen.getByRole("button", { name: "设置" }));
  await user.selectOptions(await screen.findByLabelText("CLI 类型"), "claude");
  const cliPathInput = screen.getByLabelText("CLI 路径");
  await user.clear(cliPathInput);
  await user.type(cliPathInput, "claude.cmd");
  await user.click(screen.getByRole("button", { name: "保存 CLI 配置" }));

  expect(updateCliSpy).toHaveBeenCalledWith("main", "claude", "claude.cmd");
  expect(await screen.findByText("CLI 配置已更新")).toBeInTheDocument();
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

test("settings tab can save persistent git proxy port", async () => {
  const user = userEvent.setup();
  const proxySpy = vi.spyOn(MockWebBotClient.prototype, "updateGitProxySettings");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));
  const input = await screen.findByLabelText("Git 代理端口");
  await user.clear(input);
  await user.type(input, "7897");
  await user.click(screen.getByRole("button", { name: "保存 Git 代理" }));

  expect(proxySpy).toHaveBeenCalledWith("7897");
  expect(await screen.findByText("Git 代理设置已保存")).toBeInTheDocument();
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

test("bot manager can add rename and delete managed bots", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  expect(await screen.findByRole("heading", { name: "Bot 管理" })).toBeInTheDocument();
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
  expect(screen.getByRole("heading", { name: "Bot 管理" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "main" })).not.toBeInTheDocument();
  expect(document.title).toBe("Bot 管理 - 🦞Safe Claw");

  await user.type(screen.getByLabelText("新 Bot 别名"), "team3");
  await user.type(screen.getByLabelText("Bot Token"), "333:abc");
  await user.type(screen.getByLabelText("新 Bot CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新 Bot 工作目录"), "C:\\workspace\\team3");
  await user.click(screen.getByRole("button", { name: "创建 Bot" }));

  expect(await screen.findByText("team3")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重命名 team2" }));
  const renameInput = screen.getByLabelText("team2 新别名");
  await user.clear(renameInput);
  await user.type(renameInput, "planner");
  await user.click(screen.getByRole("button", { name: "保存别名 team2" }));

  expect(await screen.findByText("planner")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "删除 planner" }));

  expect(screen.queryByText("planner")).not.toBeInTheDocument();
});

test("bot manager can create a web-only bot without telegram token", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  expect(await screen.findByRole("heading", { name: "Bot 管理" })).toBeInTheDocument();
  await user.type(screen.getByLabelText("新 Bot 别名"), "web-only");
  await user.type(screen.getByLabelText("新 Bot CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新 Bot 工作目录"), "C:\\workspace\\web-only");
  await user.click(screen.getByRole("button", { name: "创建 Bot" }));

  expect(await screen.findByText("web-only")).toBeInTheDocument();
});

test("bot manager stays open even when a stored bot alias exists", async () => {
  const user = userEvent.setup();
  localStorage.setItem("web-current-bot", "main");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });

  expect(screen.getByRole("heading", { name: "Bot 管理" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "main" })).not.toBeInTheDocument();
  expect(document.title).toBe("Bot 管理 - 🦞Safe Claw");
});

test("bot manager highlights offline bots and blocks entering them", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockResolvedValue([
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
      status: "offline",
      workingDir: "C:\\workspace\\plans",
      lastActiveText: "离线",
    },
  ]);

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  expect(await screen.findByText("离线")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "team2 当前离线，不可进入" })).toBeDisabled();
});

test("bot switcher disables offline bots", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockResolvedValue([
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
      status: "offline",
      workingDir: "C:\\workspace\\plans",
      lastActiveText: "离线",
    },
  ]);

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));

  expect(await screen.findByText("离线中，暂不可切换")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /team2/i })).toBeDisabled();
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

test("terminal tab keeps one shared session alive and rebuilds from the current bot workdir", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "终端" });

  await user.click(screen.getByRole("button", { name: "终端" }));

  expect(await screen.findByTestId("terminal-screen-root")).toBeInTheDocument();
  expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("1");

  await user.click(screen.getByRole("button", { name: "Git" }));
  await user.click(screen.getByRole("button", { name: "终端" }));
  expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("1");

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));
  await user.click(screen.getByRole("button", { name: "终端" }));
  expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("1");

  await user.click(screen.getByRole("button", { name: "重建终端" }));
  expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("2");
});

test("terminal immersive mode hides outer app chrome but keeps the terminal visible", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "终端" });

  await user.click(screen.getByRole("button", { name: "终端" }));
  await user.click(await screen.findByRole("button", { name: "进入沉浸模式" }));

  expect(screen.queryByRole("button", { name: "main" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "聊天" })).not.toBeInTheDocument();
  expect(screen.getByTestId("terminal-screen-root")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "退出沉浸模式" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "关闭终端" })).toBeInTheDocument();
});
