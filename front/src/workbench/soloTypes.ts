import type { ChatExecutionMode } from "../services/types";

export type SoloTabKind = "session" | "file-preview" | "git-diff";

export type SoloSessionSnapshot = {
  botAlias: string;
  executionMode: Extract<ChatExecutionMode, "native_agent">;
  conversationId: string;
  conversationTitle: string;
  workingDir: string;
  model: string;
  nativeSessionId: string;
  workspaceHistoryHead: string;
  linearIndex: number;
  rollbackSupported: boolean;
  degraded: boolean;
  degradedReason: string;
  contextStatusText: string;
};

export type SoloTab =
  | { id: "session"; kind: "session"; title: "会话信息" }
  | { id: string; kind: "file-preview"; title: string; path: string; readonly: true }
  | { id: string; kind: "git-diff"; title: string; path: string; staged: boolean; diffText: string; readonly: true };

export function soloModeStorageKey(accountId: string, botAlias: string) {
  return `tcb.workbenchProductMode.${accountId || "local"}.${botAlias}`;
}
