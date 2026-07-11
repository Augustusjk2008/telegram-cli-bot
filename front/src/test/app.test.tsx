import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../app/App";
import { DEMO_MAIN_WORKDIR, DEMO_TEAM_WORKDIR } from "../mocks/demoEnvironment";
import type { BotSummary, ChatMessage, SessionState } from "../services/types";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { soloModeStorageKey } from "../workbench/soloTypes";
import { buildWorkbenchSessionStorageKey } from "../workbench/workbenchSession";

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
    "manage_cli_params",
    "manage_register_codes",
    "admin_ops",
  ],
};

async function loginWithPasscode(user: ReturnType<typeof userEvent.setup>, passcode: string) {
  await user.type(screen.getByLabelText("访问口令"), passcode);
  await user.click(screen.getByRole("button", { name: "登录" }));
}

async function loginAsSuperAdmin(user: ReturnType<typeof userEvent.setup>) {
  await loginWithPasscode(user, "127.0.0.1");
}

async function loginAsMember(user: ReturnType<typeof userEvent.setup>) {
  await loginWithPasscode(user, "demo");
}

async function createManagedBot(user: ReturnType<typeof userEvent.setup>, alias: string) {
  await user.clear(screen.getByLabelText("新智能体别名"));
  await user.type(screen.getByLabelText("新智能体别名"), alias);
  await user.clear(screen.getByLabelText("新智能体 CLI 路径"));
  await user.type(screen.getByLabelText("新智能体 CLI 路径"), "codex");
  await user.clear(screen.getByLabelText("新智能体工作目录"));
  await user.type(screen.getByLabelText("新智能体工作目录"), `C:\\workspace\\${alias}`);
  await user.click(screen.getByRole("button", { name: "创建智能体" }));
}

function nativeBotSummary(alias = "pi"): BotSummary {
  return {
    alias,
    cliType: "codex",
    status: "running",
    workingDir: `C:\\workspace\\${alias}`,
    lastActiveText: "运行中",
    cliPath: "codex",
    supportedExecutionModes: ["cli", "native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
    },
    canOperate: true,
    effectiveCapabilities: SUPER_ADMIN_SESSION.capabilities,
  };
}

function mockNativeDesktopSession(bot: BotSummary) {
  vi.spyOn(MockWebBotClient.prototype, "login").mockResolvedValue({
    ...SUPER_ADMIN_SESSION,
    accountId: "acct-1",
    currentBotAlias: bot.alias,
  });
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockResolvedValue([bot]);
  vi.spyOn(MockWebBotClient.prototype, "getBotOverview").mockImplementation(async (_botAlias, options = {}) => ({
    ...bot,
    cliPath: bot.cliPath,
    enabled: true,
    isMain: false,
    messageCount: 0,
    historyCount: 0,
    isProcessing: false,
    runningReply: null,
    agents: [{ id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true }],
    activeAgentId: options.agentId || "main",
    busyAgentIds: [],
    busyAgentNames: [],
    busyAgentCount: 0,
    executionMode: options.executionMode || bot.defaultExecutionMode || "native_agent",
    globalPromptPresets: [],
  }));
}

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
  expect(sessionStorage.getItem("web-api-token")).toBeNull();
  expect(sessionStorage.getItem("web-session-token")).toBeNull();
  expect(localStorage.getItem("web-api-token")).toBeNull();
  expect(localStorage.getItem("web-session-token")).toBeNull();
});

test("restores legacy token once and clears storage after successful migration", async () => {
  sessionStorage.setItem("web-api-token", "legacy-session-token");

  render(<App />);

  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(sessionStorage.getItem("web-api-token")).toBeNull();
  expect(sessionStorage.getItem("web-session-token")).toBeNull();
  expect(localStorage.getItem("web-api-token")).toBeNull();
  expect(localStorage.getItem("web-session-token")).toBeNull();
});



test("guest login trims member-only navigation", async () => {
  const user = userEvent.setup();

  render(<App />);

  await user.click(screen.getByRole("button", { name: "以 guest 进入" }));

  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "文件" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "设置" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "main" }));
  expect(await screen.findByRole("dialog", { name: "智能体切换" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "智能体管理" })).not.toBeInTheDocument();
});

test("member with current bot access can open bot settings", async () => {
  const user = userEvent.setup();

  render(<App />);

  await loginAsMember(user);

  expect(await screen.findByRole("button", { name: "设置" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "设置" }));
  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
});

test("forced desktop mode mounts the desktop shell instead of the mobile bottom navigation", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();

  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByTestId("desktop-workbench-root")).toBeInTheDocument();
});

test("native desktop bot auto enters solo workbench", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();
  const bot = nativeBotSummary("pi");
  mockNativeDesktopSession(bot);

  render(<App />);

  await loginAsSuperAdmin(user);

  expect(await screen.findByTestId("solo-workbench-root")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Solo 模式" })).toHaveAttribute("aria-pressed", "true");
});

test("build solo switch persists per account and does not create conversations", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();
  const bot = nativeBotSummary("pi");
  mockNativeDesktopSession(bot);
  const createConversation = vi.spyOn(MockWebBotClient.prototype, "createConversation");

  render(<App />);

  await loginAsSuperAdmin(user);
  expect(await screen.findByTestId("solo-workbench-root")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "构建模式" }));
  expect(await screen.findByTestId("desktop-workbench-root")).toBeInTheDocument();
  expect(localStorage.getItem(soloModeStorageKey("acct-1", "pi"))).toBe("build");

  await user.click(screen.getByRole("button", { name: "Solo 模式" }));
  expect(await screen.findByTestId("solo-workbench-root")).toBeInTheDocument();
  expect(localStorage.getItem(soloModeStorageKey("acct-1", "pi"))).toBe("solo");
  expect(createConversation).not.toHaveBeenCalled();
});




test("desktop read-only session does not restore or open editor tabs", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  localStorage.setItem(buildWorkbenchSessionStorageKey("main", DEMO_MAIN_WORKDIR), JSON.stringify({
    version: 1,
    botAlias: "main",
    workspaceRoot: DEMO_MAIN_WORKDIR,
    sidebarView: "files",
    expandedPaths: [],
    selectedTreePath: "README.md",
    activeTabPath: "README.md",
    tabs: [
      {
        path: "README.md",
        dirty: false,
        savedContent: "RESTORED_APP_TAB",
        contentPersistence: "clean_snapshot",
      },
    ],
    focusedPane: "editor",
  }));
  const user = userEvent.setup();
  const loginSpy = vi.spyOn(MockWebBotClient.prototype, "login").mockResolvedValue({
    ...SUPER_ADMIN_SESSION,
    capabilities: SUPER_ADMIN_SESSION.capabilities.filter((capability) => capability !== "read_file_content"),
  });
  const readFileFull = vi.spyOn(MockWebBotClient.prototype, "readFileFull");
  const readFile = vi.spyOn(MockWebBotClient.prototype, "readFile");

  render(<App />);

  await loginAsSuperAdmin(user);
  expect(loginSpy).toHaveBeenCalled();
  expect(await screen.findByTestId("desktop-workbench-root")).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: /README\.md/ })).not.toBeInTheDocument();
  expect(screen.queryByText("RESTORED_APP_TAB")).not.toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "打开 README.md" })).toBeInTheDocument();
  expect(readFile).not.toHaveBeenCalled();
  expect(readFileFull).not.toHaveBeenCalled();
  expect(screen.queryByTestId("desktop-pane-editor")).not.toBeInTheDocument();
});

test("member can enter ungranted bot in read-only mode and hits create quota copy", async () => {
  const user = userEvent.setup();
  const seedClient = new MockWebBotClient();
  const baseBots = await seedClient.listBots();
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockResolvedValue(
    baseBots.map((bot) => (bot.alias === "team2" ? { ...bot, canOperate: false } : bot)),
  );

  render(<App />);

  await loginAsMember(user);
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  expect(await screen.findByText("无权限 · 只读")).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: /team2/i }));

  expect(screen.getAllByRole("button", { name: "发送" }).every((button) => button.hasAttribute("disabled"))).toBe(true);

  await user.click(screen.getByRole("button", { name: "team2" }));
  await user.click(await screen.findByRole("button", { name: "智能体管理" }));
  await screen.findByRole("heading", { name: "智能体管理" });

  for (let index = 1; index <= 9; index += 1) {
    await createManagedBot(user, `owned${index}`);
    await waitFor(() => {
      expect(screen.getByLabelText("新智能体别名")).toHaveValue("");
    });
  }
  expect(await screen.findByText("智能体已创建")).toBeInTheDocument();

  await createManagedBot(user, "owned10");
  expect(await screen.findByText("普通用户最多只能创建 10 个 Bot")).toBeInTheDocument();
}, 20_000);

test("create bot unsafe bypass toggle defaults off and submits checked value", async () => {
  const user = userEvent.setup();
  const addBot = vi.spyOn(MockWebBotClient.prototype, "addBot");

  render(<App />);

  await loginAsSuperAdmin(user);
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "智能体管理" }));
  await screen.findByRole("heading", { name: "智能体管理" });

  const toggle = screen.getByLabelText("新智能体默认绕过审批和沙箱");
  expect(toggle).not.toBeChecked();
  expect(toggle).not.toBeDisabled();

  await user.selectOptions(screen.getByLabelText("运行后端"), "native_agent");
  expect(screen.queryByLabelText("新智能体默认绕过审批和沙箱")).not.toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("运行后端"), "cli");

  await user.click(screen.getByLabelText("新智能体默认绕过审批和沙箱"));
  await createManagedBot(user, "unsafe1");

  await waitFor(() => {
    expect(addBot).toHaveBeenCalledWith(expect.objectContaining({
      alias: "unsafe1",
      bypassApprovalAndSandbox: true,
    }));
  });
  await waitFor(() => {
    expect(screen.getByLabelText("新智能体默认绕过审批和沙箱")).not.toBeChecked();
  });
});

test("create bot unsafe bypass toggle is disabled without unsafe capability", async () => {
  const user = userEvent.setup();
  const addBot = vi.spyOn(MockWebBotClient.prototype, "addBot");
  vi.spyOn(MockWebBotClient.prototype, "login").mockResolvedValue({
    ...SUPER_ADMIN_SESSION,
    accountId: "limited-manager",
    username: "limited-manager",
    token: "mock-session-limited-manager",
    isLocalAdmin: false,
    capabilities: [
      ...SUPER_ADMIN_SESSION.capabilities.filter((capability) => capability !== "admin_ops" && capability !== "run_unsafe_cli"),
      "manage_bots",
      "create_workdir_directory",
    ],
  });

  render(<App />);

  await loginWithPasscode(user, "limited-manager");
  await screen.findByRole("button", { name: "聊天" });

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "智能体管理" }));
  await screen.findByRole("heading", { name: "智能体管理" });

  const toggle = screen.getByLabelText("新智能体默认绕过审批和沙箱");
  expect(toggle).not.toBeChecked();
  expect(toggle).toBeDisabled();

  await createManagedBot(user, "safe1");

  await waitFor(() => {
    expect(addBot).toHaveBeenCalledWith(expect.objectContaining({
      alias: "safe1",
      bypassApprovalAndSandbox: false,
    }));
  });
});







