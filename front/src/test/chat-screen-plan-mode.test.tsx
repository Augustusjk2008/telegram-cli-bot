import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, ConversationSelectResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

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
  return {
    ...createOverview(),
    cluster: {
      enabled: true,
      writePolicy: "main_only",
      conflictPolicy: "warn_only",
      maxParallelAgents: 2,
      defaultTimeoutSeconds: 120,
      modelTiers: { low: "", medium: "", high: "" },
    },
    agents: [
      {
        id: "main",
        name: "主 agent",
        systemPrompt: "",
        enabled: true,
        isMain: true,
      },
    ],
  };
}

function createConversation(id: string, title: string) {
  const now = new Date().toISOString();
  return {
    id,
    title,
    lastMessagePreview: "",
    messageCount: 0,
    pinned: false,
    active: true,
    status: "active",
    botAlias: "main",
    botMode: "cli",
    cliType: "codex",
    workingDir: "C:\\workspace",
    createdAt: now,
    updatedAt: now,
  };
}

function createClient(overrides: Record<string, unknown> = {}): PlanClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    getBotOverview: async () => createOverview(),
    listMessages: async () => [],
    listConversations: async () => ({
      activeConversationId: "",
      items: [],
    }),
    createConversation: async () => ({
      conversation: createConversation("conv-new", "新会话"),
      messages: [],
    }),
    selectConversation: async () => ({
      conversation: createConversation("conv-selected", "旧会话"),
      messages: [],
    }),
    ...overrides,
  }) as PlanClient;
}

test("sends chat with plan task mode when plan mode is active", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn(async () => ({
    id: "assistant-plan",
    role: "assistant" as const,
    text: "先确认范围",
    createdAt: new Date().toISOString(),
    state: "done" as const,
  }));
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

test("shows execute and edit actions for final plan drafts", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("<PLAN_DRAFT>\n# 方案\n- 改 A\n</PLAN_DRAFT>");
      return {
        id: "assistant-plan",
        role: "assistant" as const,
        text: "<PLAN_DRAFT>\n# 方案\n- 改 A\n</PLAN_DRAFT>",
        createdAt: new Date().toISOString(),
        state: "done" as const,
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "计划模式" }));
  await user.type(screen.getByPlaceholderText("输入消息"), "先出方案");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("候选方案")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "执行方案" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "修改方案" })).toBeInTheDocument();
  expect(screen.queryByText(/PLAN_DRAFT/)).not.toBeInTheDocument();
});

test("execute plan creates a fresh conversation and auto-sends execution prompt", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn()
    .mockResolvedValueOnce({
      id: "assistant-plan",
      role: "assistant" as const,
      text: "<PLAN_DRAFT>\n# 方案\n- 改 A\n</PLAN_DRAFT>",
      createdAt: new Date().toISOString(),
      state: "done" as const,
    })
    .mockResolvedValueOnce({
      id: "assistant-done",
      role: "assistant" as const,
      text: "已执行",
      createdAt: new Date().toISOString(),
      state: "done" as const,
    });
  const executePlan = vi.fn(async () => ({
    planPath: "docs/plan/2026-05-21-1010-plan.md",
    conversation: createConversation("conv-exec", "执行方案"),
    messages: [],
    executionMessage: "请按方案执行。方案文件：docs/plan/2026-05-21-1010-plan.md",
  }));
  const client = createClient({ sendMessage, executePlan });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "计划模式" }));
  await user.type(screen.getByPlaceholderText("输入消息"), "先出方案");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await user.click(await screen.findByRole("button", { name: "执行方案" }));

  await waitFor(() => {
    expect(executePlan).toHaveBeenCalledWith("main", expect.objectContaining({
      content: "# 方案\n- 改 A",
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

test("execute plan keeps cluster enabled but leaves plan mode", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn()
    .mockResolvedValueOnce({
      id: "assistant-plan",
      role: "assistant" as const,
      text: "<PLAN_DRAFT>\n# 方案\n- 改 A\n</PLAN_DRAFT>",
      createdAt: new Date().toISOString(),
      state: "done" as const,
    })
    .mockResolvedValueOnce({
      id: "assistant-done",
      role: "assistant" as const,
      text: "已执行",
      createdAt: new Date().toISOString(),
      state: "done" as const,
    });
  const executePlan = vi.fn(async () => ({
    planPath: "docs/plan/2026-05-21-1010-plan.md",
    conversation: createConversation("conv-exec", "执行方案"),
    messages: [],
    executionMessage: "请按方案执行。方案文件：docs/plan/2026-05-21-1010-plan.md",
  }));
  const client = createClient({
    getBotOverview: async () => createClusterOverview(),
    sendMessage,
    executePlan,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "计划模式" }));
  await user.type(screen.getByPlaceholderText("@ 可指定智能体集群"), "先出方案");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await user.click(await screen.findByRole("button", { name: "执行方案" }));

  await waitFor(() => {
    expect(sendMessage).toHaveBeenLastCalledWith(
      "main",
      expect.stringContaining("请按方案执行"),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ cluster: true, taskMode: "standard" }),
    );
  });
});
