import { act, render, screen, waitFor, within } from "@testing-library/react";
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

test("renders standalone login screen without backend", async () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Orbit Safe Claw 🦞" })).toBeInTheDocument();
  expect(screen.getByText("你的随身智能体指挥中心")).toBeInTheDocument();
  expect(await screen.findByText((content) => content.includes("demo @ Windows 11"))).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes("AMD64"))).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes("16 逻辑核心 · 32 GB 内存"))).toBeInTheDocument();
  expect(screen.getByText("输入访问口令，管理本地主 Bot 与子 Bot。")).toBeInTheDocument();
  expect(screen.queryByText("输入访问口令，继续管理本地主 Bot 与子 Bot。")).not.toBeInTheDocument();
  expect(screen.queryByText("LOCAL AGENT CONTROL SURFACE")).not.toBeInTheDocument();
  expect(screen.queryByText("本地运行")).not.toBeInTheDocument();
  expect(screen.queryByText("双 CLI 支持")).not.toBeInTheDocument();
  expect(screen.queryByText("手机浏览器直接访问，无需任何 App。")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("火箭徽标")).not.toBeInTheDocument();
  expect(screen.queryByText("【志在空间 威震长空】")).not.toBeInTheDocument();
  expect(screen.queryByText("安全边界")).not.toBeInTheDocument();
  expect(screen.queryByText("自主可控")).not.toBeInTheDocument();
  expect(screen.queryByText("过程留痕")).not.toBeInTheDocument();
  expect(screen.getByLabelText("访问口令")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
  expect(document.title).toBe("Orbit Safe Claw");
  expect(document.documentElement.dataset.theme).toBe("deep-space");
});

test("keeps rendering the login shell when storage reads and writes fail", () => {
  vi.spyOn(window.sessionStorage, "getItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  vi.spyOn(window.sessionStorage, "removeItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  vi.spyOn(window.localStorage, "removeItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });

  render(<App />);

  expect(screen.getByRole("heading", { name: "Orbit Safe Claw 🦞" })).toBeInTheDocument();
  expect(screen.queryByLabelText("火箭徽标")).not.toBeInTheDocument();
  expect(screen.getByLabelText("访问口令")).toBeInTheDocument();
  expect(document.title).toBe("Orbit Safe Claw");
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

test("forced desktop mode mounts the desktop shell instead of the mobile bottom navigation", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByTestId("desktop-workbench-root")).toBeInTheDocument();
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
});

test("mobile shell exposes a layout toggle that can switch into desktop mode", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByRole("button", { name: "文件" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "桌面版" }));

  expect(await screen.findByTestId("desktop-workbench-root")).toBeInTheDocument();
});

test("desktop bot switching requires confirmation when there are dirty editor tabs", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();
  const confirmSpy = vi.spyOn(window, "confirm")
    .mockReturnValueOnce(false)
    .mockReturnValueOnce(true);
  vi.spyOn(MockWebBotClient.prototype, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [{ name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" }],
  });
  vi.spyOn(MockWebBotClient.prototype, "readFileFull").mockResolvedValue({
    content: "README",
    mode: "cat",
    fileSizeBytes: 128,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  const editor = await screen.findByLabelText("文件内容");
  await user.type(editor, " dirty");

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));

  expect(confirmSpy).toHaveBeenCalledWith("当前桌面工作台有未保存文件，切换 Bot 会丢失这些修改。确定继续吗？");
  expect(screen.getByRole("button", { name: "main" })).toBeInTheDocument();
  expect(await screen.findByText("切换 Bot")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /team2/i }));
  expect(await screen.findByRole("button", { name: "team2" })).toBeInTheDocument();
});

test("app shell is no longer constrained to a fixed mobile width", async () => {
  const user = userEvent.setup();
  const { container } = render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  const shell = container.firstElementChild;
  expect(shell).not.toBeNull();
  expect(shell?.className).toContain("w-full");
  expect(shell?.className).not.toContain("max-w-md");
  expect(shell?.className).not.toContain("mx-auto");
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

test("chat screen cache evicts older bots after switching across many bots", async () => {
  const user = userEvent.setup();
  const bots = [
    {
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\main",
      lastActiveText: "运行中",
    },
    {
      alias: "team2",
      cliType: "claude",
      status: "running",
      workingDir: "C:\\workspace\\team2",
      lastActiveText: "运行中",
    },
    {
      alias: "team3",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\team3",
      lastActiveText: "运行中",
    },
    {
      alias: "team4",
      cliType: "claude",
      status: "running",
      workingDir: "C:\\workspace\\team4",
      lastActiveText: "运行中",
    },
  ];
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockResolvedValue(bots);
  const getBotOverviewSpy = vi.spyOn(MockWebBotClient.prototype, "getBotOverview").mockImplementation(
    async (botAlias: string) => ({
      alias: botAlias,
      cliType: botAlias === "team2" || botAlias === "team4" ? "claude" : "codex",
      status: "running",
      workingDir: `C:\\workspace\\${botAlias}`,
      isProcessing: false,
    }),
  );

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  for (const alias of ["team2", "team3", "team4", "main"]) {
    await user.click(screen.getByRole("button", { name: /main|team2|team3|team4/i }));
    await user.click(await screen.findByRole("button", { name: new RegExp(alias, "i") }));
  }

  const aliases = getBotOverviewSpy.mock.calls.map(([alias]) => alias);
  expect(aliases.filter((alias) => alias === "main")).toHaveLength(2);
  expect(aliases.filter((alias) => alias === "team2")).toHaveLength(1);
  expect(aliases.filter((alias) => alias === "team3")).toHaveLength(1);
  expect(aliases.filter((alias) => alias === "team4")).toHaveLength(1);
});

test("settings tab shows cli params and tunnel status", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));

  expect(await screen.findByText("界面与阅读")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "深空轨道" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "经典暖色" })).toBeInTheDocument();
  expect(screen.getAllByText("深空轨道")).toHaveLength(1);
  expect(screen.getAllByText("经典暖色")).toHaveLength(1);
  expect(screen.getByLabelText("聊天正文字体")).toHaveValue("sans");
  expect(screen.getByLabelText("聊天正文字号")).toHaveValue("medium");
  expect(screen.getByLabelText("聊天行间距")).toHaveValue("normal");
  expect(screen.getByLabelText("聊天段间距")).toHaveValue("normal");
  expect(screen.getByRole("option", { name: "系统默认" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "宋体阅读" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "楷体阅读" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "仿宋阅读" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "代码字体" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "无衬线" })).not.toBeInTheDocument();
  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
  expect(screen.getByLabelText("推理努力程度")).toBeInTheDocument();
  expect(screen.getByText("公网访问")).toBeInTheDocument();
  expect(screen.getByText("https://demo.trycloudflare.com")).toBeInTheDocument();
});

test("main settings can switch and persist appearance preferences", async () => {
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

  await user.selectOptions(screen.getByLabelText("聊天正文字体"), "kai");
  expect(localStorage.getItem("web-chat-body-font-family")).toBe("kai");
  expect(await screen.findByText("聊天正文字体已更新")).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("聊天正文字号"), "large");
  expect(localStorage.getItem("web-chat-body-font-size")).toBe("large");
  expect(document.documentElement.style.getPropertyValue("--chat-body-font-family")).toBe('"KaiTi", "Kaiti SC", "STKaiti", serif');
  expect(document.documentElement.style.getPropertyValue("--chat-body-font-size")).toBe("17px");
  expect(await screen.findByText("聊天正文字号已更新")).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("聊天行间距"), "relaxed");
  expect(localStorage.getItem("web-chat-body-line-height")).toBe("relaxed");
  expect(document.documentElement.style.getPropertyValue("--chat-body-line-height")).toBe("2.1");
  expect(await screen.findByText("聊天行间距已更新")).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("聊天段间距"), "relaxed");
  expect(localStorage.getItem("web-chat-body-paragraph-spacing")).toBe("relaxed");
  expect(document.documentElement.style.getPropertyValue("--chat-body-paragraph-spacing")).toBe("1.1em");
  expect(await screen.findByText("聊天段间距已更新")).toBeInTheDocument();
});

test("team2 settings hide the main appearance module", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));
  await user.click(screen.getByRole("button", { name: "设置" }));

  expect(screen.queryByText("界面与阅读")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("聊天正文字体")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("聊天正文字号")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("聊天行间距")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("聊天段间距")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "深空轨道" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "经典暖色" })).not.toBeInTheDocument();
  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
});

test("re-mounting app restores persisted appearance preferences", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));
  await user.click(await screen.findByRole("button", { name: "经典暖色" }));
  await user.selectOptions(screen.getByLabelText("聊天正文字体"), "kai");
  await user.selectOptions(screen.getByLabelText("聊天正文字号"), "small");
  await user.selectOptions(screen.getByLabelText("聊天行间距"), "tight");
  await user.selectOptions(screen.getByLabelText("聊天段间距"), "relaxed");

  expect(document.documentElement.dataset.theme).toBe("classic");
  expect(document.documentElement.style.getPropertyValue("--chat-body-font-family")).toBe('"KaiTi", "Kaiti SC", "STKaiti", serif');
  expect(document.documentElement.style.getPropertyValue("--chat-body-font-size")).toBe("14px");
  expect(document.documentElement.style.getPropertyValue("--chat-body-line-height")).toBe("1.65");
  expect(document.documentElement.style.getPropertyValue("--chat-body-paragraph-spacing")).toBe("1.1em");

  unmount();
  sessionStorage.clear();
  render(<App />);
  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });
  await user.click(screen.getByRole("button", { name: "设置" }));

  expect(screen.getByLabelText("聊天正文字体")).toHaveValue("kai");
  expect(screen.getByLabelText("聊天正文字号")).toHaveValue("small");
  expect(screen.getByLabelText("聊天行间距")).toHaveValue("tight");
  expect(screen.getByLabelText("聊天段间距")).toHaveValue("relaxed");

  expect(document.documentElement.dataset.theme).toBe("classic");
  expect(document.documentElement.style.getPropertyValue("--chat-body-font-family")).toBe('"KaiTi", "Kaiti SC", "STKaiti", serif');
  expect(document.documentElement.style.getPropertyValue("--chat-body-font-size")).toBe("14px");
  expect(document.documentElement.style.getPropertyValue("--chat-body-line-height")).toBe("1.65");
  expect(document.documentElement.style.getPropertyValue("--chat-body-paragraph-spacing")).toBe("1.1em");
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

  expect(document.title).toBe("main - Orbit Safe Claw");

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

  expect(workdirSpy).toHaveBeenNthCalledWith(1, "main", "C:\\workspace\\updated", {});
  expect(await screen.findByRole("dialog", { name: "确认切换工作目录" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "确认并切换" }));
  expect(workdirSpy).toHaveBeenNthCalledWith(2, "main", "C:\\workspace\\updated", { forceReset: true });
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
        cliType: "codex",
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
        cliType: "codex",
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
  expect(screen.getByText("codex: C:\\workspace\\demo")).toBeInTheDocument();
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

  expect(within(screen.getByRole("button", { name: "team2" })).getByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "team2" }));
  expect(await screen.findByText("未读")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /main/i }));
  expect(await screen.findByText("后台完成")).toBeInTheDocument();
  expect(within(screen.getByRole("button", { name: "main" })).queryByTestId("bot-switcher-unread-indicator")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "main" }));
  expect(screen.queryByText("未读")).not.toBeInTheDocument();
});

test("desktop header shows an unread indicator when another bot has unread messages", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "sendMessage").mockImplementation(
    async (_botAlias: string, _text: string, _onChunk: (chunk: string) => void): Promise<ChatMessage> =>
      new Promise((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-hidden-desktop",
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
  await screen.findByTestId("desktop-workbench-root");

  await user.type(screen.getByPlaceholderText("输入消息"), "继续处理");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));

  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  });

  expect(within(screen.getByRole("button", { name: "team2" })).getByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "team2" }));
  await user.click(await screen.findByRole("button", { name: /main/i }));
  await screen.findByText("后台完成");

  expect(within(screen.getByRole("button", { name: "main" })).queryByTestId("bot-switcher-unread-indicator")).not.toBeInTheDocument();
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
  expect(document.title).toBe("Bot 管理 - Orbit Safe Claw");

  await user.type(screen.getByLabelText("新 Bot 别名"), "team3");
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

test("newly created bot can be entered immediately from bot manager", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  await user.type(screen.getByLabelText("新 Bot 别名"), "team3");
  await user.type(screen.getByLabelText("新 Bot CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新 Bot 工作目录"), "C:\\workspace\\team3");
  await user.click(screen.getByRole("button", { name: "创建 Bot" }));

  expect(await screen.findByText("team3")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "进入 team3" }));

  expect(await screen.findByRole("button", { name: "team3" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Bot 管理" })).not.toBeInTheDocument();
  expect(document.title).toBe("team3 - Orbit Safe Claw");
});

test("create bot form no longer asks for telegram token", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  expect(await screen.findByRole("heading", { name: "Bot 管理" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Bot Token")).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("新 Bot 别名"), "web-only");
  await user.type(screen.getByLabelText("新 Bot CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新 Bot 工作目录"), "C:\\workspace\\web-only");
  await user.click(screen.getByRole("button", { name: "创建 Bot" }));

  expect(await screen.findByText("web-only")).toBeInTheDocument();
});

test("bot manager preserves Linux-style create paths", async () => {
  const user = userEvent.setup();
  const addBotSpy = vi.spyOn(MockWebBotClient.prototype, "addBot");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  await user.type(screen.getByLabelText("新 Bot 别名"), "team-path");
  await user.type(screen.getByLabelText("新 Bot CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新 Bot 工作目录"), "/srv/telegram-cli-bridge/team3");
  await user.click(screen.getByRole("button", { name: "创建 Bot" }));

  expect(addBotSpy).toHaveBeenCalledWith(expect.objectContaining({
    alias: "team-path",
    cliPath: "codex",
    workingDir: "/srv/telegram-cli-bridge/team3",
  }));
});

test("bot manager uses compact avatar dropdowns and saves avatar choices immediately", async () => {
  const user = userEvent.setup();
  const addBotSpy = vi.spyOn(MockWebBotClient.prototype, "addBot");
  const updateAvatarSpy = vi.spyOn(MockWebBotClient.prototype, "updateBotAvatar");

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "Bot 管理" }));

  expect(await screen.findByRole("heading", { name: "Bot 管理" })).toBeInTheDocument();
  const createSection = screen.getByRole("heading", { name: "新增 Bot" }).closest("section");
  expect(createSection).not.toBeNull();
  const createScope = within(createSection as HTMLElement);
  expect(createScope.queryByText("规格固定为 64x64，建议使用 PNG/JPG/WebP。")).not.toBeInTheDocument();
  expect(createScope.getByRole("button", { name: "新 Bot 头像" })).toBeInTheDocument();
  expect(createScope.queryByRole("button", { name: "选择头像 claude-blue.png" })).not.toBeInTheDocument();
  expect(createScope.getByRole("img", { name: "新 Bot 头像预览" })).toHaveAttribute("src", "/assets/avatars/bot-default.png");

  await user.click(createScope.getByRole("button", { name: "新 Bot 头像" }));
  await user.click(createScope.getByRole("button", { name: "选择头像 claude-blue.png" }));

  expect(createScope.getByRole("img", { name: "新 Bot 头像预览" })).toHaveAttribute("src", "/assets/avatars/claude-blue.png");

  await user.type(screen.getByLabelText("新 Bot 别名"), "team-avatar");
  await user.type(screen.getByLabelText("新 Bot CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新 Bot 工作目录"), "C:\\workspace\\team-avatar");
  await user.click(screen.getByRole("button", { name: "创建 Bot" }));

  expect(addBotSpy).toHaveBeenCalledWith(expect.objectContaining({
    alias: "team-avatar",
    avatarName: "claude-blue.png",
  }));
  expect(await screen.findByRole("img", { name: "team-avatar 头像" })).toBeInTheDocument();

  const teamSection = screen.getByRole("heading", { name: "team2" }).closest("section");
  expect(teamSection).not.toBeNull();
  const teamScope = within(teamSection as HTMLElement);
  expect(teamScope.queryByText(/^CLI:/)).not.toBeInTheDocument();
  expect(teamScope.queryByText(/^目录:/)).not.toBeInTheDocument();
  const actionRow = teamScope.getByTestId("bot-actions-team2");
  expect(within(actionRow).getByRole("button", { name: "进入 team2" })).toBeInTheDocument();
  expect(within(actionRow).getByRole("button", { name: "停止 team2" })).toBeInTheDocument();
  expect(within(actionRow).getByRole("button", { name: "重命名 team2" })).toBeInTheDocument();
  expect(within(actionRow).getByRole("button", { name: "删除 team2" })).toBeInTheDocument();
  await user.click(teamScope.getByRole("button", { name: "team2 头像" }));
  await user.click(teamScope.getByRole("button", { name: "选择头像 codex-slate.png" }));

  expect(updateAvatarSpy).toHaveBeenCalledWith("team2", "codex-slate.png");
  expect(await screen.findByText("已更新 team2 的头像")).toBeInTheDocument();
});

test("settings can change my avatar and chat uses the selected image", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));

  expect(await screen.findByRole("heading", { name: "我的头像" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "我的头像预览" })).toHaveAttribute("src", "/assets/avatars/user-default.png");
  await user.click(screen.getByRole("button", { name: "我的头像" }));
  await user.click(screen.getByRole("button", { name: "选择头像 claude-blue.png" }));
  expect(screen.getByRole("img", { name: "我的头像预览" })).toHaveAttribute("src", "/assets/avatars/claude-blue.png");
  expect(localStorage.getItem("web-user-avatar-name")).toBe("claude-blue.png");

  await user.click(screen.getByRole("button", { name: "聊天" }));
  await user.type(screen.getByPlaceholderText("输入消息"), "测试头像");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("测试头像")).toBeInTheDocument();
  const userAvatars = screen.getAllByRole("img", { name: "你 头像" });
  expect(userAvatars.length).toBeGreaterThan(0);
  expect(userAvatars.every((avatar) => avatar.getAttribute("src") === "/assets/avatars/claude-blue.png")).toBe(true);
});

test("bot switcher and bot-specific pages show avatars before bot names", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  expect(screen.getAllByRole("img", { name: "main 头像" }).length).toBeGreaterThan(0);

  await user.click(screen.getByRole("button", { name: "文件" }));
  expect((await screen.findAllByRole("img", { name: "main 头像" })).length).toBeGreaterThan(0);

  await user.click(screen.getByRole("button", { name: "Git" }));
  expect((await screen.findAllByRole("img", { name: "main 头像" })).length).toBeGreaterThan(0);

  await user.click(screen.getByRole("button", { name: "main" }));
  expect(await screen.findByRole("img", { name: "team2 头像" })).toBeInTheDocument();
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
  expect(document.title).toBe("Bot 管理 - Orbit Safe Claw");
});

test("bot manager highlights offline bots and blocks entering them", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockResolvedValue([
    {
      alias: "main",
      cliType: "codex",
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
      cliType: "codex",
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
  await waitFor(() => {
    expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("1");
  });

  await user.click(screen.getByRole("button", { name: "Git" }));
  await user.click(screen.getByRole("button", { name: "终端" }));
  await waitFor(() => {
    expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("1");
  });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));
  await user.click(screen.getByRole("button", { name: "终端" }));
  await waitFor(() => {
    expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("1");
  });

  await user.click(screen.getByRole("button", { name: "重建终端" }));
  await waitFor(() => {
    expect(screen.getByTestId("terminal-instance-id")).toHaveTextContent("2");
  });
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
