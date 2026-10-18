import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ConversationListResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

const { useVoiceSessionMock, voiceSession } = vi.hoisted(() => {
  const session = {
    connected: true,
    task: "idle" as const,
    taskBinding: null,
    continuity: "stable" as const,
    end: vi.fn(),
  };
  return {
    voiceSession: session,
    useVoiceSessionMock: vi.fn(() => session),
  };
});

vi.mock("../components/CodexVoiceBar", () => ({
  CodexVoiceBar: () => null,
}));

vi.mock("../workbench/useCodexVoiceSession", () => ({
  useCodexVoiceSession: useVoiceSessionMock,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.restoreAllMocks();
  voiceSession.end.mockClear();
  useVoiceSessionMock.mockClear();
});

test("opening conversation history during voice keeps the voice session enabled", async () => {
  const user = userEvent.setup();
  const historyLoad = deferred<ConversationListResult>();
  let conversationCalls = 0;
  const listConversations = vi.fn<WebBotClient["listConversations"]>(async () => {
    conversationCalls += 1;
    if (conversationCalls === 1) {
      return { activeConversationId: "conversation-voice", items: [] };
    }
    return historyLoad.promise;
  });
  const client = Object.assign(new MockWebBotClient(), {
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex_server",
      status: "running",
      workingDir: "C:\\workspace",
      supportedExecutionModes: ["cli"],
      defaultExecutionMode: "cli",
      executionMode: "cli",
      voice: { enabled: true, reason: "available" },
      effectiveCapabilities: ["chat_send"],
    }),
    listMessages: async () => ({ items: [] }),
    listConversations,
  }) as WebBotClient;

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByRole("button", { name: "查看会话历史" });
  expect(useVoiceSessionMock).toHaveBeenLastCalledWith(expect.objectContaining({ enabled: true }));

  await user.click(screen.getByRole("button", { name: "查看会话历史" }));
  await waitFor(() => expect(screen.getAllByRole("button", { name: "关闭历史会话" }).length).toBeGreaterThan(0));
  await waitFor(() => expect(useVoiceSessionMock).toHaveBeenLastCalledWith(expect.objectContaining({ enabled: true })));
  expect(voiceSession.end).not.toHaveBeenCalled();

  await act(async () => historyLoad.resolve({ activeConversationId: "conversation-voice", items: [] }));
});
