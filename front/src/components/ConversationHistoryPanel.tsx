import { useEffect } from "react";
import { History, LoaderCircle, MessageSquarePlus, Pin, Search, X } from "lucide-react";
import type { ConversationSummary } from "../services/types";

type Props = {
  open: boolean;
  loading: boolean;
  conversations: ConversationSummary[];
  query: string;
  disabled?: boolean;
  onQueryChange: (query: string) => void;
  onClose: () => void;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
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
  onQueryChange,
  onClose,
  onNewConversation,
  onSelectConversation,
}: Props) {
  useEffect(() => {
    if (!open) {
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

  if (!open) {
    return null;
  }

  return (
    <div className="workbench-dialog-backdrop absolute inset-0 z-30 flex items-end bg-black/20 sm:items-stretch sm:bg-black/10">
      <aside className="workbench-sheet-panel flex max-h-[85%] w-full flex-col rounded-t-2xl border-t border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)] sm:h-full sm:max-h-none sm:w-[360px] sm:rounded-none sm:border-r sm:border-t-0">
        <header className="border-b border-[var(--border)] p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
              <History className="h-4 w-4" />
              <span>历史会话</span>
            </div>
            <button
              type="button"
              aria-label="关闭历史会话"
              onClick={onClose}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--surface-strong)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2">
            <Search className="h-4 w-4 text-[var(--muted)]" />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索会话"
              className="h-9 min-w-0 flex-1 bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--muted)]"
            />
          </div>
          <button
            type="button"
            disabled={disabled}
            onClick={onNewConversation}
            className="mt-3 inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-3 text-sm font-medium text-white disabled:opacity-60"
          >
            <MessageSquarePlus className="h-4 w-4" />
            新会话
          </button>
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
            {conversations.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-current={item.active ? "true" : undefined}
                aria-label={`${item.title || "新会话"} ${item.lastMessagePreview || ""}`.trim()}
                disabled={disabled}
                onClick={() => onSelectConversation(item.id)}
                className={item.active
                  ? "w-full rounded-lg border border-[var(--accent)] bg-[var(--surface-strong)] p-3 text-left disabled:opacity-60"
                  : "w-full rounded-lg border border-transparent p-3 text-left hover:bg-[var(--surface-strong)] disabled:opacity-60"}
              >
                <div className="flex min-w-0 items-center gap-2">
                  {item.pinned ? <Pin className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" /> : null}
                  <span className="truncate text-sm font-medium text-[var(--text)]">{item.title || "新会话"}</span>
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
            ))}
          </div>
        </div>
      </aside>
      <button type="button" aria-label="关闭历史会话" className="hidden flex-1 sm:block" onClick={onClose} />
    </div>
  );
}
