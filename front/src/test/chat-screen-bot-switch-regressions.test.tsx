import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    agents: [{
      id: "main",
      name: "主 agent",
      systemPrompt: "",
      enabled: true,
      isMain: true,
    }],
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
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

class ControlledResizeObserver {
  constructor(_callback: ResizeObserverCallback) {}

  observe(_target: Element) {}

  unobserve(_target: Element) {}

  disconnect() {}
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

test("keeps queued reveal scrolling after cached bot layout lowers scrollTop without user intent", async () => {
  const frameCallbacks = new Map<number, FrameRequestCallback>();
  let nextFrameId = 1;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const frameId = nextFrameId;
    nextFrameId += 1;
    frameCallbacks.set(frameId, callback);
    return frameId;
  });
  vi.stubGlobal("cancelAnimationFrame", (frameId: number) => {
    frameCallbacks.delete(frameId);
  });
  vi.stubGlobal("ResizeObserver", ControlledResizeObserver);

  const messages: ChatMessage[] = Array.from({ length: 24 }, (_, index) => ({
    id: `quick-switch-message-${index}`,
    role: index % 2 === 0 ? "user" : "assistant",
    text: `快速切换消息 ${index}`,
    createdAt: "2026-07-14T08:00:00.000Z",
    state: "done",
  }));
  const client = createClient();
  vi.spyOn(client, "getBotOverview").mockResolvedValue(createOverview());
  vi.spyOn(client, "listMessages").mockResolvedValue(messages);

  function Harness({ visible }: { visible: boolean }) {
    return (
      <div className={visible ? "block" : "hidden"}>
        <ChatScreen botAlias="main" client={client} isVisible={visible} />
      </div>
    );
  }

  const { rerender } = render(<Harness visible />);
  expect(await screen.findByText("快速切换消息 23")).toBeInTheDocument();

  const scrollContainer = screen.getByTestId("chat-scroll-container");
  let scrollTop = 0;
  let stableLayout = true;
  const maxScrollTop = () => Math.max(0, scrollContainer.scrollHeight - scrollContainer.clientHeight);
  Object.defineProperties(scrollContainer, {
    clientHeight: {
      configurable: true,
      get: () => 600,
    },
    scrollHeight: {
      configurable: true,
      get: () => (stableLayout ? 2200 : 1200),
    },
    scrollTop: {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = Math.max(0, Math.min(value, maxScrollTop()));
      },
    },
  });

  scrollContainer.scrollTop = scrollContainer.scrollHeight;
  fireEvent.scroll(scrollContainer);

  rerender(<Harness visible={false} />);
  stableLayout = false;
  rerender(<Harness visible />);
  await waitFor(() => {
    expect(scrollTop).toBe(maxScrollTop());
  });

  stableLayout = true;
  scrollContainer.scrollTop = 100;
  fireEvent.scroll(scrollContainer);

  expect(frameCallbacks.size).toBeGreaterThan(0);
  let drainedFrameCount = 0;
  await act(async () => {
    while (frameCallbacks.size > 0 && drainedFrameCount < 10) {
      const next = frameCallbacks.entries().next().value as [number, FrameRequestCallback] | undefined;
      if (!next) break;
      const [frameId, callback] = next;
      frameCallbacks.delete(frameId);
      callback(performance.now());
      drainedFrameCount += 1;
    }
  });

  expect(frameCallbacks.size).toBe(0);
  expect(drainedFrameCount).toBeLessThan(10);
  expect(scrollTop).toBe(maxScrollTop());
});

test("keeps queued reveal scrolling after a pointer tap leaves no user scroll", async () => {
  const frameCallbacks = new Map<number, FrameRequestCallback>();
  let nextFrameId = 1;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const frameId = nextFrameId;
    nextFrameId += 1;
    frameCallbacks.set(frameId, callback);
    return frameId;
  });
  vi.stubGlobal("cancelAnimationFrame", (frameId: number) => {
    frameCallbacks.delete(frameId);
  });
  vi.stubGlobal("ResizeObserver", ControlledResizeObserver);

  const messages: ChatMessage[] = Array.from({ length: 24 }, (_, index) => ({
    id: `pointer-tap-message-${index}`,
    role: index % 2 === 0 ? "user" : "assistant",
    text: `指针轻触消息 ${index}`,
    createdAt: "2026-07-14T08:00:00.000Z",
    state: "done",
  }));
  const client = createClient();
  vi.spyOn(client, "getBotOverview").mockResolvedValue(createOverview());
  vi.spyOn(client, "listMessages").mockResolvedValue(messages);

  function Harness({ visible }: { visible: boolean }) {
    return (
      <div className={visible ? "block" : "hidden"}>
        <ChatScreen botAlias="main" client={client} isVisible={visible} />
      </div>
    );
  }

  const { rerender } = render(<Harness visible />);
  expect(await screen.findByText("指针轻触消息 23")).toBeInTheDocument();

  const scrollContainer = screen.getByTestId("chat-scroll-container");
  let scrollTop = 0;
  let stableLayout = true;
  const maxScrollTop = () => Math.max(0, scrollContainer.scrollHeight - scrollContainer.clientHeight);
  Object.defineProperties(scrollContainer, {
    clientHeight: {
      configurable: true,
      get: () => 600,
    },
    scrollHeight: {
      configurable: true,
      get: () => (stableLayout ? 2200 : 1200),
    },
    scrollTop: {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = Math.max(0, Math.min(value, maxScrollTop()));
      },
    },
  });

  scrollContainer.scrollTop = scrollContainer.scrollHeight;
  fireEvent.scroll(scrollContainer);

  rerender(<Harness visible={false} />);
  stableLayout = false;
  rerender(<Harness visible />);
  await waitFor(() => {
    expect(scrollTop).toBe(maxScrollTop());
  });
  expect(frameCallbacks.size).toBeGreaterThan(0);

  fireEvent.pointerDown(scrollContainer);
  fireEvent.pointerUp(scrollContainer);
  scrollContainer.scrollTop = 100;
  fireEvent.scroll(scrollContainer);
  stableLayout = true;

  expect(frameCallbacks.size).toBeGreaterThan(0);
  let drainedFrameCount = 0;
  await act(async () => {
    while (frameCallbacks.size > 0 && drainedFrameCount < 10) {
      const next = frameCallbacks.entries().next().value as [number, FrameRequestCallback] | undefined;
      if (!next) break;
      const [frameId, callback] = next;
      frameCallbacks.delete(frameId);
      callback(performance.now());
      drainedFrameCount += 1;
    }
  });

  expect(frameCallbacks.size).toBe(0);
  expect(drainedFrameCount).toBeLessThan(10);
  expect(scrollTop).toBe(maxScrollTop());
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
