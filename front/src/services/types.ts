export type BotSummary = {
  alias: string;
  cliType: "kimi" | "claude" | "codex";
  status: "running" | "busy" | "offline";
  workingDir: string;
  lastActiveText: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  createdAt: string;
  state?: "done" | "streaming" | "error";
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
