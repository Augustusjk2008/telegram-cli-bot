import type {
  BrowserNotificationPermission,
  ChatCompletedNotificationEvent,
  WebNotificationEvent,
} from "../services/types";

export const CHAT_COMPLETION_WEB_NOTIFICATION_KEY = "tcb-chat-completion-web-notifications-enabled";
const DEDUPE_STORAGE_PREFIX = "tcb-chat-notification-dedupe:";
const DEDUPE_CHANNEL_NAME = "tcb-chat-notification-dedupe";
const DEFAULT_DEDUPE_TTL_MS = 5 * 60 * 1000;

const memoryDedupe = new Map<string, number>();
let dedupeChannel: BroadcastChannel | null | undefined;

function safeLocalStorageGet(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeLocalStorageSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Keep memory dedupe if storage is blocked.
  }
}

function openDedupeChannel() {
  if (dedupeChannel !== undefined) {
    return dedupeChannel;
  }
  if (typeof BroadcastChannel === "undefined") {
    dedupeChannel = null;
    return dedupeChannel;
  }
  try {
    dedupeChannel = new BroadcastChannel(DEDUPE_CHANNEL_NAME);
    dedupeChannel.onmessage = (event) => {
      const data = event.data as { key?: unknown; expiresAt?: unknown };
      if (typeof data.key === "string" && typeof data.expiresAt === "number") {
        memoryDedupe.set(data.key, data.expiresAt);
      }
    };
  } catch {
    dedupeChannel = null;
  }
  return dedupeChannel;
}

function cleanupDedupe(now: number) {
  for (const [key, expiresAt] of memoryDedupe) {
    if (expiresAt <= now) {
      memoryDedupe.delete(key);
    }
  }
}

export function readChatCompletionWebNotificationEnabled() {
  const raw = safeLocalStorageGet(CHAT_COMPLETION_WEB_NOTIFICATION_KEY);
  return raw !== "false";
}

export function writeChatCompletionWebNotificationEnabled(enabled: boolean) {
  safeLocalStorageSet(CHAT_COMPLETION_WEB_NOTIFICATION_KEY, enabled ? "true" : "false");
  try {
    window.dispatchEvent(new Event("chat-notification-settings-changed"));
  } catch {
    // ignore event dispatch failures
  }
}

export function getBrowserNotificationPermission(): BrowserNotificationPermission {
  if (typeof Notification === "undefined") {
    return "unsupported";
  }
  return Notification.permission;
}

export async function requestBrowserNotificationPermission(): Promise<BrowserNotificationPermission> {
  if (typeof Notification === "undefined" || typeof Notification.requestPermission !== "function") {
    return "unsupported";
  }
  try {
    return await Notification.requestPermission();
  } catch {
    return getBrowserNotificationPermission();
  }
}

export function isChatCompletedNotificationEvent(event: WebNotificationEvent): event is ChatCompletedNotificationEvent {
  return (
    event.type === "chat_completed"
    && typeof event.id === "string"
    && typeof event.dedupeKey === "string"
    && typeof event.botAlias === "string"
  );
}

export function reserveChatNotificationDedupe(
  dedupeKey: string,
  now = Date.now(),
  ttlMs = DEFAULT_DEDUPE_TTL_MS,
) {
  const key = dedupeKey.trim();
  if (!key) {
    return true;
  }

  cleanupDedupe(now);
  const memoryExpiresAt = memoryDedupe.get(key) || 0;
  if (memoryExpiresAt > now) {
    return false;
  }

  const storageKey = `${DEDUPE_STORAGE_PREFIX}${key}`;
  const stored = safeLocalStorageGet(storageKey);
  if (stored) {
    const parsed = Number(stored);
    if (Number.isFinite(parsed) && parsed > now) {
      memoryDedupe.set(key, parsed);
      return false;
    }
  }

  const expiresAt = now + ttlMs;
  memoryDedupe.set(key, expiresAt);
  safeLocalStorageSet(storageKey, String(expiresAt));
  try {
    openDedupeChannel()?.postMessage({ key, expiresAt });
  } catch {
    // localStorage and memory already cover this tab.
  }
  return true;
}

export function formatChatNotificationBody(event: ChatCompletedNotificationEvent) {
  const parts = [
    event.botAlias ? `Bot: ${event.botAlias}` : "",
    event.agentId ? `Agent: ${event.agentId}` : "",
    event.preview || "",
  ].filter(Boolean);
  return parts.join("\n");
}
