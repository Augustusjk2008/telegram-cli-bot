import type { ChatMessage, ConversationSummary } from "../../services/types";

type ConversationOverrides = Partial<ConversationSummary>;
type MessageOverrides = Partial<ChatMessage>;

export function createConversation(overrides: ConversationOverrides = {}): ConversationSummary {
  const createdAt = overrides.createdAt || new Date().toISOString();
  return {
    id: "conv_1",
    title: "新会话",
    lastMessagePreview: "",
    messageCount: 0,
    pinned: false,
    active: true,
    status: "active",
    botAlias: "main",
    botMode: "cli",
    cliType: "codex",
    workingDir: "C:\\workspace",
    createdAt,
    updatedAt: overrides.updatedAt || createdAt,
    ...overrides,
  };
}

export function createChatMessage(overrides: MessageOverrides = {}): ChatMessage {
  return {
    id: "msg_1",
    role: "assistant",
    text: "",
    createdAt: new Date().toISOString(),
    state: "done",
    ...overrides,
  };
}

export function createAssistantMessage(text = "已完成", overrides: MessageOverrides = {}): ChatMessage {
  return createChatMessage({ role: "assistant", text, ...overrides });
}

export function createUserMessage(text = "你好", overrides: MessageOverrides = {}): ChatMessage {
  return createChatMessage({ role: "user", text, ...overrides });
}
