import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { buildMockPlanExecutionMessage, createMockPlanExecuteResult, MOCK_PLAN_MARKDOWN, wrapPlanDraft } from "../mocks/planModeData";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, ConversationSelectResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { createMainAgent } from "./fixtures/agents";
import {
  createClusterConfig,
  createClusterOverview as createClusterOverviewFixture,
} from "./fixtures/cluster";
import { createAssistantMessage, createConversation } from "./fixtures/conversations";

type PlanClient = WebBotClient & {
  executePlan?: (botAlias: string, input: { content: string; title?: string; agentId?: string }) => Promise<{
    planPath: string;
    conversation: ConversationSelectResult["conversation"];
    messages: ChatMessage[];
    executionMessage: string;
  }>;
};

function createOverview(): BotOverview {
  return {
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
  };
}

function createClusterOverview(): BotOverview {
  return createClusterOverviewFixture({
    alias: "main",
    cliType: "codex",
    workingDir: "C:\\workspace",
    isProcessing: false,
    cluster: createClusterConfig({
      conflictPolicy: "warn_only",
      maxParallelAgents: 2,
      defaultTimeoutSeconds: 120,
    }),
    agents: [createMainAgent()],
  });
}

function createClient(overrides: Partial<PlanClient> = {}): PlanClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    getBotOverview: async () => createOverview(),
    listMessages: async () => [],
    listConversations: async () => ({
      activeConversationId: "",
      items: [],
    }),
    createConversation: async () => ({
      conversation: createConversation({ id: "conv-new", title: "新会话" }),
      messages: [],
    }),
    selectConversation: async () => ({
      conversation: createConversation({ id: "conv-selected", title: "旧会话" }),
      messages: [],
    }),
    ...overrides,
  }) as PlanClient;
}

beforeEach(() => {
  window.localStorage.clear();
});


test("sends chat with plan task mode when plan mode is active", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn(async () => createAssistantMessage("先确认范围", { id: "assistant-plan" }));
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "计划模式" }));
  await user.type(screen.getByPlaceholderText("输入消息"), "先出方案");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => {
    expect(sendMessage).toHaveBeenCalledWith(
      "main",
      "先出方案",
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ taskMode: "plan" }),
    );
  });
});



test("execute plan creates a fresh conversation and auto-sends execution prompt", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn()
    .mockResolvedValueOnce(createAssistantMessage(wrapPlanDraft(MOCK_PLAN_MARKDOWN), { id: "assistant-plan" }))
    .mockResolvedValueOnce(createAssistantMessage("已执行", { id: "assistant-done" }));
  const executePlan = vi.fn(async () => createMockPlanExecuteResult(
    createConversation({ id: "conv-exec", title: "执行方案" }),
    { executionMessage: buildMockPlanExecutionMessage() },
  ));
  const client = createClient({ sendMessage, executePlan });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "计划模式" }));
  await user.type(screen.getByPlaceholderText("输入消息"), "先出方案");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await user.click(await screen.findByRole("button", { name: "执行方案" }));

  await waitFor(() => {
    expect(executePlan).toHaveBeenCalledWith("main", expect.objectContaining({
      content: MOCK_PLAN_MARKDOWN,
    }));
  });
  await waitFor(() => {
    expect(sendMessage).toHaveBeenLastCalledWith(
      "main",
      expect.stringContaining("请按方案执行"),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ taskMode: "standard" }),
    );
  });
});

