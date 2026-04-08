import type { BotSummary, ChatMessage, FileEntry, SessionState } from "./types";

export interface WebBotClient {
  login(password: string): Promise<SessionState>;
  listBots(): Promise<BotSummary[]>;
  listMessages(botAlias: string): Promise<ChatMessage[]>;
  sendMessage(botAlias: string, text: string, onChunk: (chunk: string) => void): Promise<ChatMessage>;
  listFiles(botAlias: string, path: string): Promise<FileEntry[]>;
}
