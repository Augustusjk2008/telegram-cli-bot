import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../app/App";
import type { BotSummary, ChatMessage, SessionState } from "../services/types";
import { MockWebBotClient } from "../services/mockWebBotClient";

const terminalSessionMock = vi.hoisted(() => ({
  sendControl: vi.fn(),
  sendText: vi.fn(),
  fit: vi.fn(),
  focus: vi.fn(),
  dispose: vi.fn(),
  scrollToBottom: vi.fn(),
  setTheme: vi.fn(),
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
    setTheme: terminalSessionMock.setTheme,
  })),
}));

beforeEach(() => {
  terminalSessionMock.sendControl.mockReset();
  terminalSessionMock.sendText.mockReset();
  terminalSessionMock.fit.mockReset();
  terminalSessionMock.focus.mockReset();
  terminalSessionMock.dispose.mockReset();
  terminalSessionMock.scrollToBottom.mockReset();
  terminalSessionMock.setTheme.mockReset();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

const SUPER_ADMIN_SESSION: SessionState = {
  currentBotAlias: "main",
  currentPath: "/",
  isLoggedIn: true,
  token: "mock-session-super-admin",
  username: "127.0.0.1",
  role: "member",
  capabilities: [
    "view_bots",
    "view_bot_status",
    "view_file_tree",
    "mutate_browse_state",
    "view_chat_history",
    "view_chat_trace",
    "read_file_content",
    "write_files",
    "chat_send",
    "terminal_exec",
    "debug_exec",
    "git_ops",
    "run_scripts",
    "manage_cli_params",
    "manage_register_codes",
    "admin_ops",
  ],
};

test("shows bottom navigation after entering demo app shell", async () => {
  render(<App />);
  await userEvent.type(screen.getByLabelText("访问口令"), "123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "文件" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "终端" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Git" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "插件" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "设置" })).toBeInTheDocument();
  expect(sessionStorage.getItem("web-api-token")).toBe("123");
  expect(localStorage.getItem("web-api-token")).toBeNull();
});

test("guest login trims member-only navigation", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.click(screen.getByRole("button", { name: "以 guest 进入" }));

  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "文件" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "设置" })).not.toBeInTheDocument();
});

test("forced desktop mode mounts the desktop shell instead of the mobile bottom navigation", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByTestId("desktop-workbench-root")).toBeInTheDocument();
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

  expect(confirmSpy).toHaveBeenCalledWith("当前桌面工作台有未保存文件，切换智能体会丢失这些修改。确定继续吗？");
  expect(screen.getByRole("button", { name: "main" })).toBeInTheDocument();
  expect(await screen.findByText("智能体切换")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /team2/i }));
  expect(await screen.findByRole("button", { name: "team2" })).toBeInTheDocument();
});

test("super admin can open invite code management from bot switcher", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "login").mockResolvedValue({ ...SUPER_ADMIN_SESSION });

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "127.0.0.1");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "邀请码管理" }));

  expect(await screen.findByRole("heading", { name: "邀请码管理" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "返回" })).toBeInTheDocument();
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
  await user.click(await screen.findByRole("button", { name: "智能体管理" }));

  expect(await screen.findByRole("heading", { name: "智能体管理" })).toBeInTheDocument();

  await user.type(screen.getByLabelText("新智能体别名"), "team3");
  await user.type(screen.getByLabelText("新智能体 CLI 路径"), "codex");
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\team3");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

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

test("settings can change my avatar and chat uses the selected image", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "设置" }));

  expect(await screen.findByRole("heading", { name: "我的头像" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "我的头像预览" })).toHaveAttribute("src", "/assets/avatars/avatar_01.png");
  await user.click(screen.getByRole("button", { name: "我的头像" }));
  await user.click(screen.getByRole("button", { name: "选择头像 avatar_02.png" }));
  expect(screen.getByRole("img", { name: "我的头像预览" })).toHaveAttribute("src", "/assets/avatars/avatar_02.png");
  expect(localStorage.getItem("web-user-avatar-name")).toBe("avatar_02.png");

  await user.click(screen.getByRole("button", { name: "聊天" }));
  await user.type(screen.getByPlaceholderText("输入消息"), "测试头像");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("测试头像")).toBeInTheDocument();
  const userAvatars = screen.getAllByRole("img", { name: "你 头像" });
  expect(userAvatars.length).toBeGreaterThan(0);
  expect(userAvatars.every((avatar) => avatar.getAttribute("src") === "/assets/avatars/avatar_02.png")).toBe(true);
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
  ] satisfies BotSummary[]);

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "智能体管理" }));

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
  ] satisfies BotSummary[]);

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));

  expect(await screen.findByText("离线中，暂不可切换")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /team2/i })).toBeDisabled();
});

test("bot switcher sorts bots by main first, then status, then alias", async () => {
  const user = userEvent.setup();
  localStorage.setItem("web-unread-bots", JSON.stringify(["omega", "beta"]));
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockResolvedValue([
    {
      alias: "zeta",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\zeta",
      lastActiveText: "运行中",
    },
    {
      alias: "alpha",
      cliType: "claude",
      status: "busy",
      workingDir: "C:\\workspace\\alpha",
      lastActiveText: "处理中",
    },
    {
      alias: "gamma",
      cliType: "claude",
      status: "offline",
      workingDir: "C:\\workspace\\gamma",
      lastActiveText: "离线",
    },
    {
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\main",
      lastActiveText: "运行中",
      isMain: true,
    },
    {
      alias: "omega",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\omega",
      lastActiveText: "运行中",
    },
    {
      alias: "delta",
      cliType: "claude",
      status: "running",
      workingDir: "C:\\workspace\\delta",
      lastActiveText: "运行中",
    },
    {
      alias: "beta",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\beta",
      lastActiveText: "运行中",
    },
  ] satisfies BotSummary[]);

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await screen.findByText("智能体切换");

  const optionButtons = screen.getAllByRole("button").filter((button) => (
    button.textContent?.includes("C:\\workspace\\")
  ));
  const orderedAliases = optionButtons.map((button) => {
    const alias = ["main", "beta", "omega", "delta", "zeta", "alpha", "gamma"].find((candidate) => (
      button.textContent?.includes(candidate)
    ));
    return alias || "";
  });

  expect(orderedAliases).toEqual(["main", "beta", "omega", "delta", "zeta", "alpha", "gamma"]);
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
