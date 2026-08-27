import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App, sortBotsForSwitcher } from "../app/App";
import {
  chatUnreadStoragePrefix,
  markStoredChatRead,
  reconcileStoredChatUnread,
  recordStoredChatCompletion,
} from "../app/chatUnreadState";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  BotSummary,
  NotificationSubscription,
  NotificationSubscriptionOptions,
  WebNotificationEvent,
} from "../services/types";

type MockNotificationClientPrototype = MockWebBotClient & {
  subscribeNotifications?: (
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ) => NotificationSubscription;
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  delete (MockWebBotClient.prototype as MockNotificationClientPrototype).subscribeNotifications;
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

test("bot switcher keeps main first and sorts idle running bots by latest answer", () => {
  const bot = (alias: string, lastAnswerCompletedAt: string): BotSummary => ({
    alias,
    cliType: "codex",
    status: "running",
    activityStatus: "idle",
    workingDir: `C:\\workspace\\${alias}`,
    lastActiveText: "运行中",
    lastAnswerCompletedAt,
  });

  expect(sortBotsForSwitcher([
    bot("zeta", "2026-07-20T08:00:00Z"),
    bot("main", "2026-07-19T08:00:00Z"),
    bot("alpha", "2026-07-20T09:00:00Z"),
  ]).map(({ alias }) => alias)).toEqual(["main", "alpha", "zeta"]);
});

test("restores the current bot unread after login until it is explicitly opened", async () => {
  const user = userEvent.setup();
  reconcileStoredChatUnread("member", [
    { alias: "main", lastAnswerTerminalAt: "2026-08-27T01:00:00Z" },
  ]);
  const originalListBots = MockWebBotClient.prototype.listBots;
  vi.spyOn(MockWebBotClient.prototype, "listBots").mockImplementation(async function (this: MockWebBotClient) {
    const bots = await originalListBots.call(this);
    return bots.map((bot) => bot.alias === "main"
      ? {
          ...bot,
          lastAnswerTerminalAt: "2026-08-27T01:10:00Z",
        }
      : bot);
  });
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();
  const closeAnnouncement = screen.queryByRole("button", { name: "关闭公告" });
  if (closeAnnouncement) {
    await user.click(closeAnnouncement);
  }
  await user.click(screen.getByRole("button", { name: "main" }));
  const switcher = await screen.findByRole("dialog", { name: "智能体切换" });
  expect(within(switcher).getByText("未读")).toBeInTheDocument();
  await user.click(within(switcher).getByRole("button", { name: /main/ }));
  await waitFor(() => expect(screen.queryByTestId("bot-switcher-unread-indicator")).not.toBeInTheDocument());
});

test("a visible current-bot completion clears a stale red dot", async () => {
  const user = userEvent.setup();
  let emitNotification: ((event: WebNotificationEvent) => void) | null = null;
  recordStoredChatCompletion("member", "main", "2026-08-27T01:00:00Z", true);
  (MockWebBotClient.prototype as MockNotificationClientPrototype).subscribeNotifications = function (
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription {
    emitNotification = onEvent;
    options?.onStatus?.("open");
    return { close: vi.fn(), sendPresenceUpdate: vi.fn() };
  };
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();
  await waitFor(() => expect(emitNotification).toBeTruthy());

  act(() => emitNotification?.({
    type: "chat_completed",
    id: "visible-current-completion",
    dedupeKey: "visible-current-completion",
    botAlias: "main",
    agentId: "main",
    conversationId: "conversation-1",
    status: "success",
    title: "聊天已完成",
    preview: "回复完成",
    completedAt: "2026-08-27T01:10:00Z",
  }));

  await waitFor(() => expect(screen.queryByTestId("bot-switcher-unread-indicator")).not.toBeInTheDocument());
});

test("trusts a hidden-page notification even before React commits the visibility change", async () => {
  const user = userEvent.setup();
  let emitNotification: ((event: WebNotificationEvent) => void) | null = null;
  (MockWebBotClient.prototype as MockNotificationClientPrototype).subscribeNotifications = function (
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription {
    emitNotification = onEvent;
    options?.onStatus?.("open");
    return { close: vi.fn(), sendPresenceUpdate: vi.fn() };
  };
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await waitFor(() => expect(emitNotification).toBeTruthy());

  const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState");
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
  try {
    act(() => emitNotification?.({
      type: "chat_completed",
      id: "hidden-before-react-commit",
      dedupeKey: "hidden-before-react-commit",
      botAlias: "main",
      agentId: "main",
      conversationId: "conversation-1",
      status: "success",
      title: "聊天已完成",
      preview: "回复完成",
      completedAt: "2026-08-27T01:10:05Z",
      terminalAt: "2026-08-27T01:10:00Z",
    }));

    expect(await screen.findByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();
  } finally {
    if (originalVisibility) {
      Object.defineProperty(document, "visibilityState", originalVisibility);
    } else {
      delete (document as Document & { visibilityState?: DocumentVisibilityState }).visibilityState;
    }
  }
});

test("returning to a hidden current-bot page acknowledges its unread completion", async () => {
  const user = userEvent.setup();
  let emitNotification: ((event: WebNotificationEvent) => void) | null = null;
  (MockWebBotClient.prototype as MockNotificationClientPrototype).subscribeNotifications = function (
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription {
    emitNotification = onEvent;
    options?.onStatus?.("open");
    return { close: vi.fn(), sendPresenceUpdate: vi.fn() };
  };
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await waitFor(() => expect(emitNotification).toBeTruthy());

  let visibilityState: DocumentVisibilityState = "hidden";
  const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState");
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibilityState,
  });
  try {
    act(() => emitNotification?.({
      type: "chat_completed",
      id: "hidden-current-completion",
      dedupeKey: "hidden-current-completion",
      botAlias: "main",
      agentId: "main",
      conversationId: "conversation-1",
      status: "success",
      title: "聊天已完成",
      preview: "回复完成",
      completedAt: "2026-08-27T01:10:05Z",
      terminalAt: "2026-08-27T01:10:00Z",
    }));
    expect(await screen.findByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();

    visibilityState = "visible";
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(screen.queryByTestId("bot-switcher-unread-indicator")).not.toBeInTheDocument());
  } finally {
    if (originalVisibility) {
      Object.defineProperty(document, "visibilityState", originalVisibility);
    } else {
      delete (document as Document & { visibilityState?: DocumentVisibilityState }).visibilityState;
    }
  }
});

test("synchronizes unread and read watermarks written by another browser tab", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  recordStoredChatCompletion("member", "team2", "2026-08-27T01:10:00Z", true);
  act(() => window.dispatchEvent(new StorageEvent("storage", {
    key: `${chatUnreadStoragePrefix("member")}terminal:team2:remote`,
  })));
  expect(await screen.findByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();

  markStoredChatRead("member", "team2");
  act(() => window.dispatchEvent(new StorageEvent("storage", {
    key: `${chatUnreadStoragePrefix("member")}read:team2:remote`,
  })));
  await waitFor(() => expect(screen.queryByTestId("bot-switcher-unread-indicator")).not.toBeInTheDocument());
});

test("opening the desktop chat pane acknowledges that bot unread", async () => {
  localStorage.setItem("web-view-mode", "desktop");
  const user = userEvent.setup();
  let emitNotification: ((event: WebNotificationEvent) => void) | null = null;
  (MockWebBotClient.prototype as MockNotificationClientPrototype).subscribeNotifications = function (
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription {
    emitNotification = onEvent;
    options?.onStatus?.("open");
    return { close: vi.fn(), sendPresenceUpdate: vi.fn() };
  };
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));
  const closeAnnouncement = screen.queryByRole("button", { name: "关闭公告" });
  if (closeAnnouncement) {
    await user.click(closeAnnouncement);
  }
  await user.click(await screen.findByRole("button", { name: "隐藏右侧聊天" }));
  await waitFor(() => expect(emitNotification).toBeTruthy());

  act(() => emitNotification?.({
    type: "chat_completed",
    id: "desktop-hidden-chat",
    dedupeKey: "desktop-hidden-chat",
    botAlias: "main",
    agentId: "main",
    conversationId: "conversation-1",
    status: "success",
    title: "聊天已完成",
    preview: "回复完成",
    completedAt: "2026-08-27T01:10:05Z",
    terminalAt: "2026-08-27T01:10:00Z",
  }));
  expect(await screen.findByTestId("bot-switcher-unread-indicator")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "显示右侧聊天" }));
  await waitFor(() => expect(screen.queryByTestId("bot-switcher-unread-indicator")).not.toBeInTheDocument());
});

test("guest session exposes browsing but withholds member and admin entry points", async () => {
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

test("without unsafe CLI permission, create form disables bypass and submits false", async () => {
  const user = userEvent.setup();
  const originalLogin = MockWebBotClient.prototype.login;
  const addBot = vi.spyOn(MockWebBotClient.prototype, "addBot");
  vi.spyOn(MockWebBotClient.prototype, "login").mockImplementation(
    async function (this: MockWebBotClient, input: { username: string; password: string } | string) {
      const session = await originalLogin.call(this, input);
      return {
        ...session,
        capabilities: session.capabilities.filter((capability) => capability !== "admin_ops" && capability !== "run_unsafe_cli"),
      };
    },
  );
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await user.click(await screen.findByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "智能体管理" }));

  const bypassToggle = await screen.findByLabelText("新智能体默认绕过审批和沙箱");
  expect(bypassToggle).toBeDisabled();
  expect(bypassToggle).not.toBeChecked();

  await user.type(screen.getByLabelText("新智能体别名"), "no-unsafe");
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\no-unsafe");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => expect(addBot).toHaveBeenCalledWith(expect.objectContaining({
    alias: "no-unsafe",
    bypassApprovalAndSandbox: false,
  })));
});
