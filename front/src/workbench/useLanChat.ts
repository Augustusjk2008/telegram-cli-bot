import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  LanChatConversation,
  LanChatEvent,
  LanChatMessage,
  LanChatParticipant,
  LanChatStatus,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function appendUniqueMessage(items: LanChatMessage[], message: LanChatMessage) {
  if (items.some((item) => item.id === message.id)) {
    return items;
  }
  return [...items, message].sort((left, right) => left.seq - right.seq);
}

export function useLanChat(client: WebBotClient, visible: boolean) {
  const [status, setStatus] = useState<LanChatStatus | null>(null);
  const [conversations, setConversations] = useState<LanChatConversation[]>([]);
  const [messagesByConversation, setMessagesByConversation] = useState<Record<string, LanChatMessage[]>>({});
  const [latestEvent, setLatestEvent] = useState<LanChatEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const totalUnread = useMemo(
    () => conversations.reduce((sum, item) => sum + item.unreadCount, 0),
    [conversations],
  );

  const onlineUsers = useMemo<LanChatParticipant[]>(
    () => status?.onlineUsers || [],
    [status],
  );

  const refresh = useCallback(async () => {
    if (!visible) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [nextStatus, nextConversations] = await Promise.all([
        client.getLanChatStatus(),
        client.listLanChatConversations(),
      ]);
      setStatus(nextStatus);
      setConversations(nextConversations);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载联机聊天失败");
    } finally {
      setLoading(false);
    }
  }, [client, visible]);

  const loadMessages = useCallback(async (conversationId: string) => {
    const items = await client.listLanChatMessages(conversationId, 0, 80);
    setMessagesByConversation((prev) => ({ ...prev, [conversationId]: items }));
    return items;
  }, [client]);

  const markRead = useCallback(async (conversationId: string, seq?: number) => {
    const messages = messagesByConversation[conversationId] || [];
    const lastSeq = seq ?? messages[messages.length - 1]?.seq ?? 0;
    if (!lastSeq) {
      return;
    }
    await client.markLanChatRead(conversationId, lastSeq);
    setConversations((prev) => prev.map((item) => (
      item.id === conversationId ? { ...item, unreadCount: 0 } : item
    )));
  }, [client, messagesByConversation]);

  const sendMessage = useCallback(async (conversationId: string, text: string) => {
    const message = await client.sendLanChatMessage(conversationId, text);
    setMessagesByConversation((prev) => ({
      ...prev,
      [conversationId]: appendUniqueMessage(prev[conversationId] || [], message),
    }));
    await refresh();
    return message;
  }, [client, refresh]);

  const openPrivateConversation = useCallback(async (targetRoomUserId: string) => {
    const conversation = await client.createLanChatPrivateConversation(targetRoomUserId);
    setConversations((prev) => [
      conversation,
      ...prev.filter((item) => item.id !== conversation.id),
    ]);
    await loadMessages(conversation.id);
    return conversation;
  }, [client, loadMessages]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!visible || !client.openLanChatSocket) {
      return;
    }
    return client.openLanChatSocket((event: LanChatEvent) => {
      setLatestEvent(event);
      if (event.type === "snapshot") {
        setStatus(event.status);
      }
      if (event.type === "presence_updated") {
        if (event.status) {
          setStatus(event.status);
        }
        void refresh();
      }
      if (event.type === "message_created") {
        setMessagesByConversation((prev) => ({
          ...prev,
          [event.message.conversationId]: appendUniqueMessage(
            prev[event.message.conversationId] || [],
            event.message,
          ),
        }));
        void refresh();
      }
      if (event.type === "conversation_updated") {
        setConversations((prev) => [
          event.conversation,
          ...prev.filter((item) => item.id !== event.conversation.id),
        ]);
      }
      if (event.type === "read_updated") {
        setConversations((prev) => prev.map((item) => (
          item.id === event.conversationId ? { ...item, unreadCount: 0 } : item
        )));
      }
      if (event.type === "config_updated") {
        void refresh();
      }
    });
  }, [client, refresh, visible]);

  return {
    status,
    conversations,
    messagesByConversation,
    onlineUsers,
    totalUnread,
    latestEvent,
    loading,
    error,
    refresh,
    loadMessages,
    sendMessage,
    openPrivateConversation,
    markRead,
  };
}
