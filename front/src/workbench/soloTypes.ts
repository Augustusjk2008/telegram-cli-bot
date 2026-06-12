import type { ChatExecutionMode } from "../services/types";

export type SoloTabKind = "session" | "session-changes" | "file-preview" | "session-diff";

export type SoloSessionSnapshot = {
  botAlias: string;
  agentId: string;
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
  | { id: "changes"; kind: "session-changes"; title: "会话变更" }
  | { id: string; kind: "file-preview"; title: string; path: string; readonly: true }
  | { id: string; kind: "session-diff"; title: string; path: string; turnId: string; diffText: string; readonly: true; truncated?: boolean };

export function soloModeStorageKey(accountId: string, botAlias: string) {
  return `tcb.workbenchProductMode.${accountId || "local"}.${botAlias}`;
}
