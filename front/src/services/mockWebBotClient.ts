import type { BotSummary, ChatMessage, FileEntry, SessionState } from "./types";
import { WebBotClient } from "./webBotClient";
import { mockBots } from "../mocks/bots";

export class MockWebBotClient implements WebBotClient {
  async login(password: string): Promise<SessionState> {
    return {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      canExec: true,
      canAdmin: true,
    };
  }

  async listBots(): Promise<BotSummary[]> {
    return mockBots;
  }

  async listMessages(botAlias: string): Promise<ChatMessage[]> {
    return [];
  }

  async sendMessage(botAlias: string, text: string, onChunk: (chunk: string) => void): Promise<ChatMessage> {
    return {
      id: Date.now().toString(),
      role: "assistant",
      text: "Mock response",
      createdAt: new Date().toISOString(),
      state: "done"
    };
  }

  async listFiles(botAlias: string, path: string): Promise<FileEntry[]> {
    return [];
  }
}

export async function streamAssistantReply(onChunk: (chunk: string) => void) {
  const chunks = ["我先看一下问题。", "已经定位到可能原因。", "建议先检查 session 与工作目录。"];
  for (const chunk of chunks) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    onChunk(chunk);
  }
}
