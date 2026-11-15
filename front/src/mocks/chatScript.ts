import type { ChatMessageContextUsage, ChatTraceEvent, ClusterTeam } from "../services/types";

/**
 * Optional scripted reply for the mock client. Nothing sets it by default, so the stock mock reply is
 * unchanged; `npm run tutorial:shots` sets `window.__ORBIT_MOCK_CHAT_SCRIPT__` to capture a turn that
 * has execution details and context usage, and a conversation with a cluster team.
 */
export type MockChatScript = {
  chunks: string[];
  trace?: ChatTraceEvent[];
  contextUsage?: ChatMessageContextUsage;
  /** Team reported for main conversations created while the script is set. */
  clusterTeam?: ClusterTeam;
};

export function readMockChatScript(): MockChatScript | null {
  const script = typeof window !== "undefined"
    ? (window as Window & { __ORBIT_MOCK_CHAT_SCRIPT__?: MockChatScript }).__ORBIT_MOCK_CHAT_SCRIPT__
    : undefined;
  return script && Array.isArray(script.chunks) ? script : null;
}
