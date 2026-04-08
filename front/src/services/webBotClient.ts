import type {
  BotOverview,
  BotSummary,
  ChatMessage,
  ChatStatusUpdate,
  DirectoryListing,
  SessionState,
  SystemScript,
  SystemScriptResult,
} from "./types";

export interface WebBotClient {
  login(token: string): Promise<SessionState>;
  listBots(): Promise<BotSummary[]>;
  getBotOverview(botAlias: string): Promise<BotOverview>;
  listMessages(botAlias: string): Promise<ChatMessage[]>;
  sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
  ): Promise<ChatMessage>;
  getCurrentPath(botAlias: string): Promise<string>;
  listFiles(botAlias: string): Promise<DirectoryListing>;
  changeDirectory(botAlias: string, path: string): Promise<string>;
  readFile(botAlias: string, filename: string): Promise<string>;
  uploadFile(botAlias: string, file: File): Promise<void>;
  downloadFile(botAlias: string, filename: string): Promise<void>;
  resetSession(botAlias: string): Promise<void>;
  killTask(botAlias: string): Promise<string>;
  listSystemScripts(): Promise<SystemScript[]>;
  runSystemScript(scriptName: string): Promise<SystemScriptResult>;
}
