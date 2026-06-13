import { clsx } from "clsx";
import { RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type {
  AgentScopedOptions,
  ChatMessage,
  NativeAgentHistoryChangedFile,
  NativeAgentHistoryChangesPayload,
  NativeAgentHistoryDiffPayload,
  NativeAgentHistoryRollbackResult,
} from "../services/types";
import type { SoloSessionSnapshot } from "./soloTypes";

export type SoloSessionChangesClient = {
  listMessages(botAlias: string, options?: AgentScopedOptions): Promise<ChatMessage[]>;
  getNativeAgentHistoryChanges(
    botAlias: string,
    input: { conversationId: string; turnId: string; agentId?: string },
  ): Promise<NativeAgentHistoryChangesPayload>;
  getNativeAgentHistoryDiff(
    botAlias: string,
    input: { conversationId: string; turnId: string; path: string; agentId?: string },
  ): Promise<NativeAgentHistoryDiffPayload>;
  rollbackNativeAgentHistory(
    botAlias: string,
    input: { conversationId: string; targetTurnId: string; agentId?: string },
  ): Promise<NativeAgentHistoryRollbackResult>;
};

type Props = {
  botAlias: string;
  client: SoloSessionChangesClient;
  snapshot: SoloSessionSnapshot | null;
  historyRevision?: number;
  onOpenDiff: (turnId: string, path: string) => Promise<void>;
  onRollbackComplete?: () => void;
};

type SessionChangeTurn = {
  turnId: string;
  messageId: string;
  createdAt: string;
  linearIndex: number;
  head: string;
  userText: string;
};

function statusLabel(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "added") return "新增";
  if (normalized === "modified") return "修改";
  if (normalized === "deleted") return "删除";
  if (normalized === "renamed") return "重命名";
  if (normalized === "copied") return "复制";
  return "未知";
}

function statusClass(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "added") return "bg-emerald-500/10 text-emerald-700";
  if (normalized === "deleted") return "bg-red-500/10 text-red-700";
  if (normalized === "renamed") return "bg-amber-500/10 text-amber-700";
  if (normalized === "copied") return "bg-sky-500/10 text-sky-700";
  return "bg-[var(--surface-strong)] text-[var(--text)]";
}

const CHAT_ATTACHMENT_LINE_RE = /^附件路径为[:：]\s*(.+?)\s*$/;

function belongsToConversation(message: ChatMessage, conversationId: string) {
  return !message.conversationId || !conversationId || message.conversationId === conversationId;
}

function summarizeUserText(text: string) {
  const value = text
    .split(/\r?\n/)
    .filter((line) => !CHAT_ATTACHMENT_LINE_RE.test(line.trim()))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  if (!value) return "用户消息";
  return value.length > 80 ? `${value.slice(0, 80).trimEnd()}...` : value;
}

function buildTurns(messages: ChatMessage[], conversationId: string): SessionChangeTurn[] {
  const turns = new Map<string, SessionChangeTurn>();
  let pendingUserText = "";
  for (const message of messages) {
    if (!belongsToConversation(message, conversationId)) continue;
    if (message.role === "user") {
      pendingUserText = summarizeUserText(message.text);
      continue;
    }
    if (message.role !== "assistant") continue;
    const head = String(message.meta?.workspaceHistoryHead || "").trim();
    if (!head) continue;
    const turnId = String(message.turnId || message.id || "").trim();
    if (!turnId || turns.has(turnId)) continue;
    const linearIndex = Number(message.meta?.linearIndex || turns.size + 1);
    turns.set(turnId, {
      turnId,
      messageId: message.id,
      createdAt: message.createdAt,
      linearIndex: Number.isFinite(linearIndex) ? linearIndex : turns.size + 1,
      head,
      userText: pendingUserText || "用户消息",
    });
  }
  return [...turns.values()].sort((a, b) => a.linearIndex - b.linearIndex || a.createdAt.localeCompare(b.createdAt));
}

function fileKey(file: NativeAgentHistoryChangedFile) {
  return `${file.status}:${file.oldPath}:${file.path}`;
}

export function SoloSessionChangesTab({
  botAlias,
  client,
  snapshot,
  historyRevision = 0,
  onOpenDiff,
  onRollbackComplete,
}: Props) {
  const conversationId = snapshot?.conversationId || "";
  const agentId = snapshot?.agentId && snapshot.agentId !== "main" ? snapshot.agentId : "";
  const [turns, setTurns] = useState<SessionChangeTurn[]>([]);
  const [selectedTurnId, setSelectedTurnId] = useState("");
  const [turnsLoading, setTurnsLoading] = useState(false);
  const [turnsError, setTurnsError] = useState("");
  const [changes, setChanges] = useState<NativeAgentHistoryChangesPayload | null>(null);
  const [changesLoading, setChangesLoading] = useState(false);
  const [changesError, setChangesError] = useState("");
  const [rollbacking, setRollbacking] = useState(false);
  const [pendingRollbackTurn, setPendingRollbackTurn] = useState<SessionChangeTurn | null>(null);
  const [notice, setNotice] = useState("");

  const loadTurns = useCallback(async () => {
    if (!conversationId) {
      setTurns([]);
      setSelectedTurnId("");
      return;
    }
    setTurnsLoading(true);
    setTurnsError("");
    try {
      const messages = await client.listMessages(botAlias, {
        executionMode: "native_agent",
        ...(agentId ? { agentId } : {}),
      });
      const nextTurns = buildTurns(messages, conversationId);
      setTurns(nextTurns);
      setSelectedTurnId((current) => {
        if (current && nextTurns.some((turn) => turn.turnId === current)) return current;
        return nextTurns[nextTurns.length - 1]?.turnId || "";
      });
    } catch (err) {
      setTurnsError(err instanceof Error ? err.message : "读取会话变更失败");
      setTurns([]);
      setSelectedTurnId("");
    } finally {
      setTurnsLoading(false);
    }
  }, [agentId, botAlias, client, conversationId]);

  useEffect(() => {
    setChanges(null);
    setNotice("");
    void loadTurns();
  }, [historyRevision, loadTurns]);

  useEffect(() => {
    if (!conversationId || !selectedTurnId) {
      setChanges(null);
      setChangesError("");
      return;
    }
    let cancelled = false;
    setChangesLoading(true);
    setChangesError("");
    void client.getNativeAgentHistoryChanges(botAlias, {
      conversationId,
      turnId: selectedTurnId,
      ...(agentId ? { agentId } : {}),
    })
      .then((payload) => {
        if (!cancelled) setChanges(payload);
      })
      .catch((err) => {
        if (!cancelled) {
          setChanges(null);
          setChangesError(err instanceof Error ? err.message : "读取文件变更失败");
        }
      })
      .finally(() => {
        if (!cancelled) setChangesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, botAlias, client, conversationId, selectedTurnId]);

  const selectedTurn = useMemo(
    () => turns.find((turn) => turn.turnId === selectedTurnId) || null,
    [selectedTurnId, turns],
  );
  const latestTurn = turns[turns.length - 1] || null;
  const canRollback = Boolean(
    snapshot?.rollbackSupported
    && selectedTurn
    && latestTurn
    && selectedTurn.linearIndex < latestTurn.linearIndex,
  );

  const handleRollback = async (turn: SessionChangeTurn) => {
    if (!conversationId) return;
    setRollbacking(true);
    setNotice("");
    setChangesError("");
    try {
      const result = await client.rollbackNativeAgentHistory(botAlias, {
        conversationId,
        targetTurnId: turn.turnId,
        ...(agentId ? { agentId } : {}),
      });
      setNotice(result.message || "已撤回到所选会话点");
      setSelectedTurnId(turn.turnId);
      await loadTurns();
      onRollbackComplete?.();
    } catch (err) {
      setChangesError(err instanceof Error ? err.message : "撤回失败");
    } finally {
      setRollbacking(false);
      setPendingRollbackTurn(null);
    }
  };

  if (!snapshot) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-sm text-[var(--muted)]">
        会话变更加载中...
      </div>
    );
  }

  const rollbackDialog = pendingRollbackTurn ? (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/35 px-4">
      <div role="dialog" aria-modal="true" aria-label="确认撤回" className="w-full max-w-sm rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-4 shadow-[var(--shadow-card)]">
        <h2 className="text-sm font-semibold text-[var(--text)]">确认撤回</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">会丢弃该点之后的会话和工作区改动，不可撤销</p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setPendingRollbackTurn(null)}
            disabled={rollbacking}
            className="inline-flex h-8 items-center rounded-md border border-[var(--workbench-hairline)] px-3 text-xs text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleRollback(pendingRollbackTurn)}
            disabled={rollbacking}
            className="inline-flex h-8 items-center rounded-md bg-red-600 px-3 text-xs font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {rollbacking ? "撤回中..." : "确认撤回"}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <div data-testid="solo-session-changes-tab" className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]">
      <div className="flex min-w-0 items-center justify-between gap-3 border-b border-[var(--workbench-hairline)] px-4 py-2 text-xs text-[var(--muted)]">
        <span className="min-w-0 truncate">线性会话历史 · {turns.length} 轮</span>
        <div className="flex shrink-0 items-center gap-2">
          {canRollback ? (
            <button
              type="button"
              onClick={() => setPendingRollbackTurn(selectedTurn)}
              disabled={rollbacking}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-red-500/30 px-2 text-xs text-red-700 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              {rollbacking ? "撤回中..." : "撤回到此轮"}
            </button>
          ) : null}
          <button
            type="button"
            aria-label="刷新会话变更"
            title="刷新会话变更"
            onClick={() => void loadTurns()}
            disabled={turnsLoading}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className={clsx("h-3.5 w-3.5", turnsLoading && "animate-spin")} />
          </button>
        </div>
      </div>

      <div className="grid min-h-0 grid-cols-[minmax(13rem,18rem)_minmax(0,1fr)]">
        <aside className="min-h-0 overflow-y-auto border-r border-[var(--workbench-hairline)] bg-[var(--surface-subtle)]/40">
          {turnsLoading && turns.length === 0 ? (
            <div className="px-4 py-3 text-sm text-[var(--muted)]">读取中...</div>
          ) : turnsError ? (
            <div className="px-4 py-3 text-sm text-red-600">{turnsError}</div>
          ) : turns.length === 0 ? (
            <div className="px-4 py-3 text-sm text-[var(--muted)]">当前会话暂无可展示的变更</div>
          ) : (
            <div className="p-2">
              {turns.map((turn) => {
                const active = turn.turnId === selectedTurnId;
                return (
                  <button
                    key={turn.turnId}
                    type="button"
                    aria-label={`选择 ${turn.userText}`}
                    title={turn.userText}
                    onClick={() => setSelectedTurnId(turn.turnId)}
                    className={clsx(
                      "mb-1 block w-full min-w-0 rounded-md px-2.5 py-2 text-left text-xs transition-colors",
                      active ? "tcb-selected-accent" : "text-[var(--text)] hover:bg-[var(--surface-strong)]",
                    )}
                  >
                    <span className="block min-w-0 truncate font-medium">{turn.userText}</span>
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        <section className="min-h-0 overflow-y-auto">
          {notice ? (
            <div className="border-b border-[var(--workbench-hairline)] px-4 py-2 text-xs text-emerald-700">{notice}</div>
          ) : null}
          {changesError ? (
            <div className="px-4 py-3 text-sm text-red-600">{changesError}</div>
          ) : changesLoading ? (
            <div className="px-4 py-3 text-sm text-[var(--muted)]">读取中...</div>
          ) : !selectedTurn || !changes || changes.files.length === 0 ? (
            <div className="px-4 py-3 text-sm text-[var(--muted)]">当前会话暂无可展示的变更</div>
          ) : (
            <div className="divide-y divide-[var(--workbench-hairline)]">
              {changes.files.map((file) => (
                <button
                  key={fileKey(file)}
                  type="button"
                  aria-label={`打开 ${file.path} diff`}
                  onClick={() => void onOpenDiff(selectedTurn.turnId, file.path)}
                  className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-2 px-4 py-1.5 text-left text-xs hover:bg-[var(--surface-subtle)]"
                >
                  <span className="flex min-w-0 items-center gap-1 font-medium text-[var(--text)]">
                    <span className="min-w-0 truncate" title={file.path}>{file.path}</span>
                    {file.oldPath ? (
                      <>
                        <span className="shrink-0 text-[var(--muted)]">←</span>
                        <span className="min-w-0 truncate text-[var(--muted)]" title={file.oldPath}>{file.oldPath}</span>
                      </>
                    ) : null}
                  </span>
                  <span className={clsx("rounded px-1.5 py-0.5 text-[10px] font-medium", statusClass(file.status))}>{statusLabel(file.status)}</span>
                  <span className="font-mono text-[11px] text-emerald-700">+{file.additions}</span>
                  <span className="font-mono text-[11px] text-red-700">-{file.deletions}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
      {rollbackDialog && typeof document !== "undefined" ? createPortal(rollbackDialog, document.body) : rollbackDialog}
    </div>
  );
}
