import { useEffect, useState } from "react";
import { History, LoaderCircle, MessageSquarePlus, Pin, Search, Star, Trash2, X } from "lucide-react";
import { toolbarButtonClass } from "./ToolbarButton";
import type { ConversationSummary, FavoriteAnswerItem } from "../services/types";

export type ConversationHistoryPanelTab = "history" | "favorites";

type Props = {
  open: boolean;
  activeTab?: ConversationHistoryPanelTab;
  loading: boolean;
  favoritesLoading?: boolean;
  conversations: ConversationSummary[];
  favorites?: FavoriteAnswerItem[];
  query: string;
  disabled?: boolean;
  deletingConversationId?: string;
  deletingFavoriteId?: string;
  favoriteError?: string;
  onTabChange?: (tab: ConversationHistoryPanelTab) => void;
  onQueryChange: (query: string) => void;
  onClose: () => void;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onSelectFavorite?: (favorite: FavoriteAnswerItem) => void;
  onDeleteFavorite?: (favorite: FavoriteAnswerItem) => void;
  onDeleteConversation: (conversation: ConversationSummary, deleteNativeSession: boolean) => void;
  onDeleteAllConversations: (deleteNativeSession: boolean) => void;
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
  activeTab = "history",
  loading,
  favoritesLoading = false,
  conversations,
  favorites = [],
  query,
  disabled = false,
  deletingConversationId = "",
  deletingFavoriteId = "",
  favoriteError = "",
  onTabChange,
  onQueryChange,
  onClose,
  onNewConversation,
  onSelectConversation,
  onSelectFavorite,
  onDeleteFavorite,
  onDeleteConversation,
  onDeleteAllConversations,
}: Props) {
  const [pendingDelete, setPendingDelete] = useState<ConversationSummary | null>(null);
  const [pendingDeleteAll, setPendingDeleteAll] = useState(false);
  const [deleteNativeSession, setDeleteNativeSession] = useState(true);

  useEffect(() => {
    if (!open) {
      setPendingDelete(null);
      setPendingDeleteAll(false);
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
  const favoriteDeleting = Boolean(deletingFavoriteId);
  const deleteDialogTitle = pendingDeleteAll ? "删除全部会话" : "删除会话";
  const panelLoading = activeTab === "favorites" ? favoritesLoading : loading;
  const emptyText = activeTab === "favorites" ? "暂无收藏" : "暂无历史";
  const searchLabel = activeTab === "favorites" ? "搜索收藏" : "搜索会话";

  return (
    <div className="workbench-dialog-backdrop absolute inset-0 z-30 flex items-end bg-black/20 sm:items-stretch sm:bg-black/10">
      <aside className="workbench-sheet-panel flex max-h-[85%] w-full flex-col rounded-t-lg border-t border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-card)] sm:h-full sm:max-h-none sm:w-[380px] sm:rounded-none sm:border-r sm:border-t-0">
        <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
              <History className="h-4 w-4" />
              <span>历史会话</span>
            </div>
            <div className="ml-auto flex items-center gap-1.5">
              {activeTab === "history" ? (
                <>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setDeleteNativeSession(true);
                      setPendingDeleteAll(true);
                    }}
                    className={toolbarButtonClass("danger", "sm", "h-8")}
                  >
                    <Trash2 className="h-4 w-4" />
                    清空
                  </button>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={onNewConversation}
                    className={toolbarButtonClass("primary", "sm", "h-8")}
                  >
                    <MessageSquarePlus className="h-4 w-4" />
                    新会话
                  </button>
                </>
              ) : null}
              <button
                type="button"
                aria-label="关闭历史会话"
                onClick={onClose}
                className={toolbarButtonClass("ghost", "icon", "h-8 w-8")}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="mt-3 inline-flex rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-0.5">
            <button
              type="button"
              aria-pressed={activeTab === "history"}
              onClick={() => onTabChange?.("history")}
              className={activeTab === "history"
                ? "h-7 rounded px-3 text-xs font-medium text-[var(--accent)] bg-[var(--workbench-active-bg)]"
                : "h-7 rounded px-3 text-xs font-medium text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}
            >
              历史
            </button>
            <button
              type="button"
              aria-pressed={activeTab === "favorites"}
              onClick={() => onTabChange?.("favorites")}
              className={activeTab === "favorites"
                ? "h-7 rounded px-3 text-xs font-medium text-[var(--accent)] bg-[var(--workbench-active-bg)]"
                : "h-7 rounded px-3 text-xs font-medium text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}
            >
              收藏
            </button>
          </div>
          <div className="mt-3 flex items-center gap-2 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2">
            <Search className="h-4 w-4 text-[var(--muted)]" />
            <input
              aria-label={searchLabel}
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder={searchLabel}
              className="h-9 min-w-0 flex-1 bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--muted)]"
            />
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {panelLoading ? (
            <div role="status" className="mt-10 flex justify-center text-[var(--muted)]">
              <LoaderCircle className="h-5 w-5 animate-spin" />
              <span className="sr-only">{activeTab === "favorites" ? "加载收藏中" : "加载历史会话中"}</span>
            </div>
          ) : null}
          {activeTab === "favorites" && favoriteError ? (
            <div className="mb-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{favoriteError}</div>
          ) : null}
          {!panelLoading && (activeTab === "favorites" ? favorites.length === 0 : conversations.length === 0) ? (
            <div className="mt-10 text-center text-sm text-[var(--muted)]">{emptyText}</div>
          ) : null}
          {activeTab === "history" ? (
            <div className="space-y-1">
              {conversations.map((item) => {
              const title = item.title || "新会话";
              const itemDeleting = deletingConversationId === item.id;
              return (
                <div
                  key={item.id}
                  aria-current={item.active ? "true" : undefined}
                  className={item.active
                    ? "flex rounded-lg border border-[var(--workbench-hover-border)] bg-[var(--workbench-active-bg)] shadow-[var(--shadow-soft)] disabled:opacity-60"
                    : "flex rounded-lg border border-transparent hover:border-[var(--workbench-hairline)] hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"}
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
                    className="m-2 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-red-600 disabled:opacity-60"
                  >
                    {itemDeleting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  </button>
                </div>
              );
              })}
            </div>
          ) : (
            <div className="space-y-1">
              {favorites.map((item) => {
                const title = item.title || "新会话";
                const itemDeleting = deletingFavoriteId === item.id;
                return (
                  <div
                    key={item.id}
                    className="flex rounded-lg border border-transparent hover:border-[var(--workbench-hairline)] hover:bg-[var(--workbench-hover-bg)]"
                  >
                    <button
                      type="button"
                      aria-label={`打开收藏 ${title} ${item.preview}`.trim()}
                      disabled={disabled || favoriteDeleting}
                      onClick={() => onSelectFavorite?.(item)}
                      className="min-w-0 flex-1 p-3 text-left disabled:opacity-60"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <Star className="h-3.5 w-3.5 shrink-0 fill-current text-amber-500" />
                        <span className="truncate text-sm font-medium text-[var(--text)]">{title}</span>
                        <span className="ml-auto shrink-0 text-[11px] text-[var(--muted)]">{formatConversationTime(item.favoritedAt)}</span>
                      </div>
                      <div className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-[var(--muted)]">
                        {item.preview || item.answerText || "收藏回答"}
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-[11px] text-[var(--muted)]">
                        <span>{item.agentId || "main"}</span>
                        <span>{item.executionMode === "native_agent" ? "原生 agent" : "CLI"}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      aria-label={`取消收藏 ${title}`}
                      disabled={disabled || favoriteDeleting}
                      onClick={() => onDeleteFavorite?.(item)}
                      className="m-2 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-amber-600 hover:bg-amber-50 disabled:opacity-60"
                    >
                      {itemDeleting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Star className="h-4 w-4 fill-current" />}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </aside>
      <button type="button" aria-label="关闭历史会话" className="hidden flex-1 sm:block" onClick={onClose} />
      {pendingDelete || pendingDeleteAll ? (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/30 px-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-conversation-title"
            className="w-full max-w-sm rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-4 shadow-[var(--shadow-card)]"
          >
            <h2 id="delete-conversation-title" className="text-sm font-semibold text-[var(--text)]">{deleteDialogTitle}</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
              {pendingDeleteAll ? "将删除本 bot 当前工作区全部历史会话，影响所有可访问该 bot 的用户。" : "共享会话，删除会影响所有可访问该 bot 的用户。"}
            </p>
            <label className="mt-3 flex items-center gap-2 text-sm text-[var(--text)]">
              <input
                type="checkbox"
                checked={deleteNativeSession}
                onChange={(event) => setDeleteNativeSession(event.target.checked)}
                className="h-4 w-4 rounded border-[var(--border)]"
              />
              <span>同时清除关联会话 session 存储</span>
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                disabled={deleting}
                onClick={() => {
                  setPendingDelete(null);
                  setPendingDeleteAll(false);
                }}
                className={toolbarButtonClass("plain", "md")}
              >
                取消
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => {
                  if (pendingDeleteAll) {
                    onDeleteAllConversations(deleteNativeSession);
                    return;
                  }
                  if (pendingDelete) {
                    onDeleteConversation(pendingDelete, deleteNativeSession);
                  }
                }}
                className={toolbarButtonClass("danger", "md")}
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
