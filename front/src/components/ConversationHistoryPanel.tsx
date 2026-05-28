import { useEffect, useState } from "react";
import { History, LoaderCircle, MessageSquarePlus, Pin, Search, Trash2, X } from "lucide-react";
import type { ConversationSummary } from "../services/types";

type Props = {
  open: boolean;
  loading: boolean;
  conversations: ConversationSummary[];
  query: string;
  disabled?: boolean;
  deletingConversationId?: string;
  onQueryChange: (query: string) => void;
  onClose: () => void;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversation: ConversationSummary, deleteNativeSession: boolean) => void;
};

function formatConversationTime(value: string) {
  const parsed = Date.parse(value || "");
  if (Number.isNaN(parsed)) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(parsed));
}

export function ConversationHistoryPanel({
  open,
  loading,
  conversations,
  query,
  disabled = false,
  deletingConversationId = "",
  onQueryChange,
  onClose,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
}: Props) {
  const [pendingDelete, setPendingDelete] = useState<ConversationSummary | null>(null);
  const [deleteNativeSession, setDeleteNativeSession] = useState(true);

  useEffect(() => {
    if (!open) {
      setPendingDelete(null);
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!pendingDelete) {
      return;
    }
    if (!conversations.some((item) => item.id === pendingDelete.id)) {
      setPendingDelete(null);
    }
  }, [conversations, pendingDelete]);

  if (!open) {
    return null;
  }

  const deleting = Boolean(deletingConversationId);

  return (
    <div className="workbench-dialog-backdrop absolute inset-0 z-30 flex items-end bg-black/20 sm:items-stretch sm:bg-black/10">
      <aside className="workbench-sheet-panel flex max-h-[85%] w-full flex-col rounded-t-2xl border-t border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)] sm:h-full sm:max-h-none sm:w-[360px] sm:rounded-none sm:border-r sm:border-t-0">
        <header className="border-b border-[var(--border)] p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
              <History className="h-4 w-4" />
              <span>历史会话</span>
            </div>
            <div className="ml-auto flex items-center gap-1.5">
              <button
                type="button"
                disabled={disabled}
                onClick={onNewConversation}
                className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-60"
              >
                <MessageSquarePlus className="h-4 w-4" />
                新会话
              </button>
              <button
                type="button"
                aria-label="关闭历史会话"
                onClick={onClose}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--surface-strong)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2">
            <Search className="h-4 w-4 text-[var(--muted)]" />
            <input
              aria-label="搜索会话"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索会话"
              className="h-9 min-w-0 flex-1 bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--muted)]"
            />
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {loading ? (
            <div role="status" className="mt-10 flex justify-center text-[var(--muted)]">
              <LoaderCircle className="h-5 w-5 animate-spin" />
              <span className="sr-only">加载历史会话中</span>
            </div>
          ) : null}
          {!loading && conversations.length === 0 ? (
            <div className="mt-10 text-center text-sm text-[var(--muted)]">暂无历史</div>
          ) : null}
          <div className="space-y-1">
            {conversations.map((item) => {
              const title = item.title || "新会话";
              const itemDeleting = deletingConversationId === item.id;
              return (
                <div
                  key={item.id}
                  aria-current={item.active ? "true" : undefined}
                  className={item.active
                    ? "flex rounded-lg border border-[var(--accent)] bg-[var(--surface-strong)] disabled:opacity-60"
                    : "flex rounded-lg border border-transparent hover:bg-[var(--surface-strong)] disabled:opacity-60"}
                >
                  <button
                    type="button"
                    aria-label={`${title} ${item.lastMessagePreview || ""}`.trim()}
                    disabled={disabled || deleting}
                    onClick={() => onSelectConversation(item.id)}
                    className="min-w-0 flex-1 p-3 text-left disabled:opacity-60"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      {item.pinned ? <Pin className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" /> : null}
                      <span className="truncate text-sm font-medium text-[var(--text)]">{title}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-[var(--muted)]">{formatConversationTime(item.updatedAt)}</span>
                    </div>
                    <div className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--muted)]">
                      {item.lastMessagePreview || "尚无消息"}
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-[11px] text-[var(--muted)]">
                      <span>{item.messageCount} 条</span>
                      {item.nativeSource?.provider ? <span>{item.nativeSource.provider}</span> : null}
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label={`删除会话 ${title}`}
                    disabled={disabled || deleting}
                    onClick={() => {
                      setDeleteNativeSession(true);
                      setPendingDelete(item);
                    }}
                    className="m-2 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--bg)] hover:text-red-600 disabled:opacity-60"
                  >
                    {itemDeleting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </aside>
      <button type="button" aria-label="关闭历史会话" className="hidden flex-1 sm:block" onClick={onClose} />
      {pendingDelete ? (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/30 px-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-conversation-title"
            className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-card)]"
          >
            <h2 id="delete-conversation-title" className="text-sm font-semibold text-[var(--text)]">删除会话</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--muted)]">将删除此历史会话和本地消息记录。</p>
            <label className="mt-3 flex items-center gap-2 text-sm text-[var(--text)]">
              <input
                type="checkbox"
                checked={deleteNativeSession}
                onChange={(event) => setDeleteNativeSession(event.target.checked)}
                className="h-4 w-4 rounded border-[var(--border)]"
              />
              <span>同时清除关联 CLI session 存储</span>
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                disabled={deleting}
                onClick={() => setPendingDelete(null)}
                className="inline-flex h-9 items-center rounded-lg border border-[var(--border)] px-3 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                取消
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => onDeleteConversation(pendingDelete, deleteNativeSession)}
                className="inline-flex h-9 items-center rounded-lg bg-red-600 px-3 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
