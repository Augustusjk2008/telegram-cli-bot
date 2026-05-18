import { useCallback, useEffect, useState } from "react";
import { MessageCircle, Search, Users, X } from "lucide-react";
import type { LanChatConversation } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { LanChatWindow } from "./LanChatWindow";
import { useLanChat } from "./useLanChat";

type Props = {
  client: WebBotClient;
  visible: boolean;
};

const FALLBACK_GROUP: LanChatConversation = {
  id: "group:default",
  kind: "group",
  title: "工作室",
  participantIds: [],
  lastMessage: null,
  unreadCount: 0,
  updatedAt: "",
};

export function LanChatDock({ client, visible }: Props) {
  const [listOpen, setListOpen] = useState(false);
  const [activeConversation, setActiveConversation] = useState<LanChatConversation | null>(null);
  const [toastText, setToastText] = useState("");
  const chat = useLanChat(client, visible);

  const openConversation = useCallback(async (conversation: LanChatConversation) => {
    setActiveConversation(conversation);
    const messages = await chat.loadMessages(conversation.id);
    await chat.markRead(conversation.id, messages[messages.length - 1]?.seq);
    await chat.refresh();
  }, [chat]);

  useEffect(() => {
    if (chat.latestEvent?.type !== "message_created") {
      return;
    }
    if (activeConversation?.id === chat.latestEvent.message.conversationId) {
      return;
    }
    setToastText(`${chat.latestEvent.message.sender.displayName}: ${chat.latestEvent.message.text}`);
    const timer = window.setTimeout(() => setToastText(""), 3500);
    return () => window.clearTimeout(timer);
  }, [activeConversation?.id, chat.latestEvent]);

  if (!visible) {
    return null;
  }

  const group = chat.conversations.find((item) => item.kind === "group") || {
    ...FALLBACK_GROUP,
    title: chat.status?.roomName || FALLBACK_GROUP.title,
  };
  const dmConversations = chat.conversations.filter((item) => item.kind === "dm");

  return (
    <>
      <button
        type="button"
        aria-label={`成员聊天${chat.totalUnread > 0 ? `，${chat.totalUnread} 条未读` : ""}`}
        onClick={() => setListOpen((prev) => !prev)}
        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-0.5 text-xs hover:bg-[var(--surface-strong)]"
      >
        <MessageCircle className="h-3.5 w-3.5" />
        <span>成员聊天</span>
        {chat.totalUnread > 0 ? (
          <span className="rounded-full bg-red-500 px-1.5 text-[10px] text-white">{chat.totalUnread}</span>
        ) : null}
      </button>

      {toastText ? (
        <button
          type="button"
          onClick={() => setListOpen(true)}
          className="fixed bottom-16 right-3 z-40 max-w-80 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-left text-sm shadow-xl"
        >
          {toastText}
        </button>
      ) : null}

      {listOpen ? (
        <section
          role="dialog"
          aria-label="联机聊天列表"
          className="fixed bottom-8 right-3 z-30 flex h-[min(540px,62vh)] w-80 flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-2xl"
        >
          <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2">
            <div>
              <div className="text-sm font-semibold text-[var(--text)]">联机聊天</div>
              <div className="text-xs text-[var(--muted)]">
                {chat.status?.connected ? `${chat.onlineUsers.length} 在线` : "未连接"}
              </div>
            </div>
            <button
              type="button"
              aria-label="关闭联机聊天列表"
              onClick={() => setListOpen(false)}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-[var(--surface)]"
            >
              <X className="h-4 w-4" />
            </button>
          </header>
          <div className="border-b border-[var(--border)] p-2">
            <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-xs text-[var(--muted)]">
              <Search className="h-3.5 w-3.5" />
              <span>私聊用户在下方在线列表选择</span>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <div className="space-y-1">
              <button
                type="button"
                onClick={() => void openConversation(group)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-[var(--surface-strong)]"
              >
                <Users className="h-4 w-4 text-[var(--muted)]" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-[var(--text)]">群聊 · {group.title}</span>
                  <span className="block truncate text-xs text-[var(--muted)]">
                    {group.lastMessage?.text || "默认群聊"}
                  </span>
                </span>
                {group.unreadCount > 0 ? (
                  <span className="rounded-full bg-red-500 px-1.5 text-[10px] text-white">{group.unreadCount}</span>
                ) : null}
              </button>
              {dmConversations.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => void openConversation(conversation)}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-[var(--surface-strong)]"
                >
                  <MessageCircle className="h-4 w-4 text-[var(--muted)]" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-[var(--text)]">{conversation.title}</span>
                    <span className="block truncate text-xs text-[var(--muted)]">
                      {conversation.lastMessage?.text || "私聊"}
                    </span>
                  </span>
                  {conversation.unreadCount > 0 ? (
                    <span className="rounded-full bg-red-500 px-1.5 text-[10px] text-white">{conversation.unreadCount}</span>
                  ) : null}
                </button>
              ))}
            </div>
            <div className="mt-3 border-t border-[var(--border)] pt-2">
              <div className="px-2 py-1 text-xs font-medium text-[var(--muted)]">在线用户</div>
              {chat.onlineUsers
                .filter((user) => user.roomUserId !== chat.status?.self.roomUserId)
                .map((participant) => (
                  <button
                    key={participant.roomUserId}
                    type="button"
                    onClick={async () => {
                      const conversation = await chat.openPrivateConversation(participant.roomUserId);
                      await openConversation(conversation);
                    }}
                    className="flex w-full items-center justify-between rounded-lg px-2 py-2 text-left hover:bg-[var(--surface-strong)]"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-[var(--text)]">{participant.displayName}</span>
                      <span className="block truncate text-xs text-[var(--muted)]">{participant.instanceName}</span>
                    </span>
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  </button>
                ))}
            </div>
          </div>
          {chat.error ? (
            <div className="border-t border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{chat.error}</div>
          ) : null}
        </section>
      ) : null}

      {activeConversation ? (
        <LanChatWindow
          conversation={activeConversation}
          messages={chat.messagesByConversation[activeConversation.id] || []}
          currentRoomUserId={chat.status?.self.roomUserId}
          onLoad={() => chat.loadMessages(activeConversation.id)}
          onSend={(text) => chat.sendMessage(activeConversation.id, text)}
          onMinimize={() => setActiveConversation(null)}
          onClose={() => setActiveConversation(null)}
        />
      ) : null}
    </>
  );
}
