import { FormEvent, useEffect, useMemo, useState } from "react";
import { MessageCircle, Minus, Send, X } from "lucide-react";
import type { LanChatConversation, LanChatMessage } from "../services/types";

type Props = {
  conversation: LanChatConversation;
  messages: LanChatMessage[];
  currentRoomUserId?: string;
  onLoad: () => void | Promise<unknown>;
  onClose: () => void;
  onMinimize: () => void;
  onSend: (text: string) => void | Promise<unknown>;
};

export function LanChatWindow({
  conversation,
  messages,
  currentRoomUserId = "",
  onLoad,
  onClose,
  onMinimize,
  onSend,
}: Props) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const title = conversation.kind === "group" ? `群聊 · ${conversation.title || "工作室"}` : conversation.title || "私聊";
  const sortedMessages = useMemo(() => [...messages].sort((left, right) => left.seq - right.seq), [messages]);

  useEffect(() => {
    void onLoad();
  }, [conversation.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || sending) {
      return;
    }
    setSending(true);
    try {
      await onSend(text);
      setDraft("");
    } finally {
      setSending(false);
    }
  }

  return (
    <section
      role="dialog"
      aria-label={title}
      className="fixed bottom-8 right-96 z-30 flex h-[min(560px,64vh)] w-[420px] flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-2xl"
    >
      <header className="flex items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <MessageCircle className="h-4 w-4 shrink-0 text-[var(--muted)]" />
          <span className="truncate text-sm font-semibold text-[var(--text)]">{title}</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="最小化聊天窗"
            onClick={onMinimize}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-[var(--surface)]"
          >
            <Minus className="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label="关闭聊天窗"
            onClick={onClose}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-[var(--surface)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {sortedMessages.length === 0 ? (
          <p className="text-center text-sm text-[var(--muted)]">暂无消息</p>
        ) : sortedMessages.map((message) => {
          const mine = message.sender.roomUserId === currentRoomUserId;
          return (
            <article key={message.id} className={mine ? "flex justify-end" : "flex justify-start"}>
              <div className={mine
                ? "max-w-[78%] rounded-lg bg-[var(--accent)] px-3 py-2 text-[var(--accent-foreground)]"
                : "max-w-[78%] rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-[var(--text)]"}
              >
                {!mine ? (
                  <div className="mb-1 text-[11px] text-[var(--muted)]">
                    {message.sender.displayName} · {message.sender.instanceName}
                  </div>
                ) : null}
                <p className="whitespace-pre-wrap break-words text-sm">{message.text}</p>
              </div>
            </article>
          );
        })}
      </div>
      <form onSubmit={submit} className="border-t border-[var(--border)] bg-[var(--surface-strong)] p-2">
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="输入消息"
            rows={2}
            className="min-h-10 flex-1 resize-none rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--accent)] focus:outline-none"
          />
          <button
            type="submit"
            aria-label="发送消息"
            disabled={sending || !draft.trim()}
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent)] text-[var(--accent-foreground)] disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </form>
    </section>
  );
}
