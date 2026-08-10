import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, HistorySnapshotResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  return Object.assign(new MockWebBotClient(), overrides);
}

function createOverview(): BotOverview {
  return {
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    cliPath: "codex",
    enabled: true,
    isMain: true,
    messageCount: 0,
    historyCount: 0,
    isProcessing: false,
    runningReply: null,
    agents: [{ id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true }],
    activeAgentId: "main",
    busyAgentIds: [],
    busyAgentNames: [],
    busyAgentCount: 0,
    canOperate: true,
    effectiveCapabilities: [],
    promptPresets: [],
    globalPromptPresets: [],
    supportedExecutionModes: ["cli"],
    defaultExecutionMode: "cli",
    executionMode: "cli",
  };
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

test("restarts initial history loading after a hidden cached bot cancels the first request", async () => {
  const firstHistory = createDeferred<HistorySnapshotResult>();
  const staleHistory: ChatMessage[] = [{
    id: "stale-history-message",
    role: "assistant",
    text: "不应显示的过期历史",
    createdAt: "2026-07-14T08:00:00.000Z",
    state: "done",
  }];
  const reloadedHistory: ChatMessage[] = [{
    id: "reloaded-history-message",
    role: "assistant",
    text: "重新加载历史",
    createdAt: "2026-07-14T08:01:00.000Z",
    state: "done",
  }];
  const client = createClient();
  vi.spyOn(client, "getBotOverview").mockResolvedValue(createOverview());
  const listMessages = vi.spyOn(client, "listMessages")
    .mockImplementationOnce(() => firstHistory.promise)
    .mockResolvedValueOnce({ items: reloadedHistory });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
  await waitFor(() => {
    expect(listMessages).toHaveBeenCalledTimes(1);
  });
  expect(screen.getByText("加载中...")).toBeInTheDocument();

  rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  await act(async () => {
    firstHistory.resolve({ items: staleHistory });
    await Promise.resolve();
  });
  expect(screen.queryByText("不应显示的过期历史")).not.toBeInTheDocument();

  rerender(<ChatScreen botAlias="main" client={client} isVisible />);
  await waitFor(() => {
    expect(listMessages).toHaveBeenCalledTimes(2);
  });
  expect(await screen.findByText("重新加载历史")).toBeInTheDocument();
  expect(screen.queryByText("加载中...")).not.toBeInTheDocument();
});

test("defers auxiliary data for hidden chats and reuses it across visibility changes", async () => {
  const client = createClient();
  vi.spyOn(client, "getBotOverview").mockResolvedValue(createOverview());
  vi.spyOn(client, "listMessages").mockResolvedValue({ items: [] });
  const getCliParams = vi.spyOn(client, "getCliParams").mockResolvedValue({
    cliType: "codex",
    params: {},
    defaults: {},
    schema: {},
  });
  const listFavoriteAnswers = vi.spyOn(client, "listFavoriteAnswers").mockResolvedValue({
    items: [],
    executionMode: "cli",
  });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  await act(async () => {
    await Promise.resolve();
  });
  expect(getCliParams).not.toHaveBeenCalled();
  expect(listFavoriteAnswers).not.toHaveBeenCalled();

  rerender(<ChatScreen botAlias="main" client={client} isVisible />);
  await waitFor(() => {
    expect(getCliParams).toHaveBeenCalledTimes(1);
    expect(listFavoriteAnswers).toHaveBeenCalledTimes(1);
  });
  await screen.findByText("暂无消息，开始聊天吧");

  rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  rerender(<ChatScreen botAlias="main" client={client} isVisible />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(getCliParams).toHaveBeenCalledTimes(1);
  expect(listFavoriteAnswers).toHaveBeenCalledTimes(1);

  rerender(<ChatScreen botAlias="secondary" client={client} isVisible />);
  await waitFor(() => {
    expect(getCliParams).toHaveBeenCalledTimes(2);
    expect(listFavoriteAnswers).toHaveBeenCalledTimes(2);
  });
  expect(getCliParams).toHaveBeenLastCalledWith("secondary");
  expect(listFavoriteAnswers).toHaveBeenLastCalledWith("secondary", "", {
    agentId: "main",
    executionMode: "cli",
  });
});

test("reloads favorites for agent and execution mode scopes without reloading CLI params", async () => {
  const client = createClient();
  const overview: BotOverview = {
    ...createOverview(),
    agents: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "代码审查", systemPrompt: "", enabled: true, isMain: false },
    ],
    supportedExecutionModes: ["cli", "native_agent"],
  };
  vi.spyOn(client, "getBotOverview").mockResolvedValue(overview);
  vi.spyOn(client, "listAgents").mockResolvedValue({ items: overview.agents || [] });
  vi.spyOn(client, "listMessages").mockResolvedValue({ items: [] });
  const getCliParams = vi.spyOn(client, "getCliParams").mockResolvedValue({
    cliType: "codex",
    params: {},
    defaults: {},
    schema: {},
  });
  const listFavoriteAnswers = vi.spyOn(client, "listFavoriteAnswers").mockResolvedValue({
    items: [],
    executionMode: "cli",
  });

  render(<ChatScreen botAlias="main" client={client} isVisible />);
  await waitFor(() => expect(listFavoriteAnswers).toHaveBeenCalledTimes(1));

  fireEvent.change(await screen.findByRole("combobox", { name: "当前 agent" }), {
    target: { value: "reviewer" },
  });
  await waitFor(() => expect(listFavoriteAnswers).toHaveBeenCalledTimes(2));
  expect(listFavoriteAnswers).toHaveBeenLastCalledWith("main", "", {
    agentId: "reviewer",
    executionMode: "cli",
  });

  fireEvent.click(screen.getByRole("button", { name: "原生 agent" }));
  await waitFor(() => expect(listFavoriteAnswers).toHaveBeenCalledTimes(3));
  expect(listFavoriteAnswers).toHaveBeenLastCalledWith("main", "", {
    agentId: "reviewer",
    executionMode: "native_agent",
  });
  expect(getCliParams).toHaveBeenCalledTimes(1);
});

test("retries failed auxiliary loads on the next foreground activation", async () => {
  const client = createClient();
  vi.spyOn(client, "getBotOverview").mockResolvedValue(createOverview());
  vi.spyOn(client, "listMessages").mockResolvedValue({ items: [] });
  const getCliParams = vi.spyOn(client, "getCliParams")
    .mockRejectedValueOnce(new Error("CLI 参数加载失败"))
    .mockResolvedValue({ cliType: "codex", params: {}, defaults: {}, schema: {} });
  const listFavoriteAnswers = vi.spyOn(client, "listFavoriteAnswers")
    .mockRejectedValueOnce(new Error("收藏加载失败"))
    .mockResolvedValue({ items: [], executionMode: "cli" });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
  await waitFor(() => {
    expect(getCliParams).toHaveBeenCalledTimes(1);
    expect(listFavoriteAnswers).toHaveBeenCalledTimes(1);
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  rerender(<ChatScreen botAlias="main" client={client} isVisible />);
  await waitFor(() => {
    expect(getCliParams).toHaveBeenCalledTimes(2);
    expect(listFavoriteAnswers).toHaveBeenCalledTimes(2);
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  rerender(<ChatScreen botAlias="main" client={client} isVisible />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(getCliParams).toHaveBeenCalledTimes(2);
  expect(listFavoriteAnswers).toHaveBeenCalledTimes(2);
});
