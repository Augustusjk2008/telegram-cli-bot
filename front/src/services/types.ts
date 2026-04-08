export type BotStatus = "running" | "busy" | "offline";

export type BotSummary = {
  alias: string;
  cliType: "kimi" | "claude" | "codex";
  status: BotStatus;
  workingDir: string;
  lastActiveText: string;
};

export type BotOverview = {
  alias: string;
  cliType: "kimi" | "claude" | "codex";
  status: BotStatus;
  workingDir: string;
  botMode?: string;
  messageCount?: number;
  historyCount?: number;
  isProcessing?: boolean;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  createdAt: string;
  state?: "done" | "streaming" | "error";
};

export type SystemScript = {
  scriptName: string;
  displayName: string;
  description: string;
  path: string;
};

export type SystemScriptResult = {
  scriptName: string;
  success: boolean;
  output: string;
};

export type FileEntry = {
  name: string;
  isDir: boolean;
  size?: number;
  updatedAt?: string;
};

export type SessionState = {
  currentBotAlias: string;
  currentPath: string;
  isLoggedIn: boolean;
  canExec: boolean;
  canAdmin: boolean;
};

export type DirectoryListing = {
  workingDir: string;
  entries: FileEntry[];
};
