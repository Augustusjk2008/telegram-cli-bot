import { useEffect, useMemo, useRef, useState } from "react";
import type {
  BrowserNotificationPermission,
  NotificationPresenceUpdate,
  NotificationSocketStatus,
  NotificationSubscription,
  WebNotificationEvent,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  getBrowserNotificationPermission,
  readChatCompletionWebNotificationEnabled,
} from "../utils/chatNotificationEvents";

type UseNotificationPresenceInput = {
  client: WebBotClient;
  enabled: boolean;
  currentBotAlias?: string | null;
  onEvent: (event: WebNotificationEvent) => void;
};

function buildPresence(currentBotAlias?: string | null): NotificationPresenceUpdate {
  return {
    visible: typeof document === "undefined" ? true : document.visibilityState !== "hidden",
    focused: typeof document === "undefined" ? true : document.hasFocus(),
    permission: getBrowserNotificationPermission(),
    webNotificationsEnabled: readChatCompletionWebNotificationEnabled(),
    currentBotAlias,
    updatedAt: new Date().toISOString(),
  };
}

export function useNotificationPresence({
  client,
  enabled,
  currentBotAlias,
  onEvent,
}: UseNotificationPresenceInput) {
  const [permission, setPermission] = useState<BrowserNotificationPermission>(() => getBrowserNotificationPermission());
  const [socketStatus, setSocketStatus] = useState<NotificationSocketStatus>("closed");
  const canSubscribe = enabled && typeof client.subscribeNotifications === "function";
  const currentBotAliasRef = useRef(currentBotAlias);
  const onEventRef = useRef(onEvent);
  const subscriptionRef = useRef<NotificationSubscription | null>(null);
  currentBotAliasRef.current = currentBotAlias;
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!canSubscribe || typeof client.subscribeNotifications !== "function") {
      setSocketStatus("closed");
      return;
    }

    const subscription = client.subscribeNotifications((event) => onEventRef.current(event), {
      onStatus: setSocketStatus,
    });
    subscriptionRef.current = subscription;

    const sendPresence = () => {
      const nextPresence = buildPresence(currentBotAliasRef.current);
      setPermission(nextPresence.permission);
      subscription.sendPresenceUpdate(nextPresence);
    };

    sendPresence();
    document.addEventListener("visibilitychange", sendPresence);
    window.addEventListener("focus", sendPresence);
    window.addEventListener("blur", sendPresence);
    window.addEventListener("chat-notification-settings-changed", sendPresence);

    return () => {
      document.removeEventListener("visibilitychange", sendPresence);
      window.removeEventListener("focus", sendPresence);
      window.removeEventListener("blur", sendPresence);
      window.removeEventListener("chat-notification-settings-changed", sendPresence);
      subscriptionRef.current = null;
      subscription.close();
    };
  }, [canSubscribe, client]);

  useEffect(() => {
    if (!canSubscribe) {
      return;
    }
    const presence = buildPresence(currentBotAlias);
    setPermission(presence.permission);
    subscriptionRef.current?.sendPresenceUpdate(presence);
    client.sendNotificationPresenceUpdate?.(presence);
  }, [canSubscribe, client, currentBotAlias]);

  return useMemo(() => ({
    permission,
    socketStatus,
    supported: typeof Notification !== "undefined",
    subscribed: canSubscribe && socketStatus === "open",
  }), [canSubscribe, permission, socketStatus]);
}
