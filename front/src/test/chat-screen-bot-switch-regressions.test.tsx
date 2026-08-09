import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage } from "../services/types";
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
  const firstHistory = createDeferred<ChatMessage[]>();
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
    .mockResolvedValueOnce(reloadedHistory);

  const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
  await waitFor(() => {
    expect(listMessages).toHaveBeenCalledTimes(1);
  });
  expect(screen.getByText("加载中...")).toBeInTheDocument();

  rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  await act(async () => {
    firstHistory.resolve(staleHistory);
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
