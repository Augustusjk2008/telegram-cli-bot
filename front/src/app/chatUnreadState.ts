import type { BotSummary } from "../services/types";

const CHAT_UNREAD_STORAGE_PREFIX = "tcb-chat-unread-watermark:v2:";

export type ChatUnreadState = {
  latestTerminalAt: Record<string, string>;
  unreadBots: string[];
};

type BotCompletion = Pick<BotSummary, "alias" | "lastAnswerCompletedAt" | "lastAnswerTerminalAt">;
type MarkerKind = "terminal" | "read" | "pending";

type StoredWatermarks = {
  latestTerminalAt: Record<string, string>;
  readThroughAt: Record<string, string>;
  pendingUnreadBots: Set<string>;
};

function accountStoragePrefix(accountKey: string) {
  return `${CHAT_UNREAD_STORAGE_PREFIX}${encodeURIComponent(accountKey.trim())}:`;
}

export function chatUnreadStoragePrefix(accountKey: string) {
  return accountStoragePrefix(accountKey);
}

function initializedStorageKey(accountKey: string) {
  return `${accountStoragePrefix(accountKey)}initialized`;
}

function markerStorageKey(accountKey: string, kind: MarkerKind, alias: string, value: string) {
  return `${accountStoragePrefix(accountKey)}${kind}:${encodeURIComponent(alias)}:${encodeURIComponent(value)}`;
}

function normalizeTimestamp(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function isLaterTimestamp(candidate: string, previous: string) {
  if (!candidate || candidate === previous) {
    return false;
  }
  if (!previous) {
    return true;
  }
  const candidateTime = Date.parse(candidate);
  const previousTime = Date.parse(previous);
  if (Number.isFinite(candidateTime) && Number.isFinite(previousTime)) {
    return candidateTime > previousTime;
  }
  return candidate > previous;
}

function setLatest(target: Record<string, string>, alias: string, timestamp: string) {
  if (isLaterTimestamp(timestamp, target[alias] || "") || !target[alias]) {
    target[alias] = timestamp;
  }
}

function parseMarker(accountKey: string, key: string): { kind: MarkerKind; alias: string; value: string } | null {
  const prefix = accountStoragePrefix(accountKey);
  if (!key.startsWith(prefix)) {
    return null;
  }
  const remainder = key.slice(prefix.length);
  const kindSeparator = remainder.indexOf(":");
  const valueSeparator = remainder.indexOf(":", kindSeparator + 1);
  if (kindSeparator <= 0 || valueSeparator <= kindSeparator + 1) {
    return null;
  }
  const kind = remainder.slice(0, kindSeparator);
  if (kind !== "terminal" && kind !== "read" && kind !== "pending") {
    return null;
  }
  try {
    const alias = decodeURIComponent(remainder.slice(kindSeparator + 1, valueSeparator)).trim();
    const value = decodeURIComponent(remainder.slice(valueSeparator + 1)).trim();
    return alias && value ? { kind, alias, value } : null;
  } catch {
    return null;
  }
}

function readWatermarks(accountKey: string): StoredWatermarks {
  const watermarks: StoredWatermarks = {
    latestTerminalAt: {},
    readThroughAt: {},
    pendingUnreadBots: new Set(),
  };
  const normalizedAccountKey = accountKey.trim();
  if (!normalizedAccountKey) {
    return watermarks;
  }
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key) {
        continue;
      }
      const marker = parseMarker(normalizedAccountKey, key);
      if (!marker) {
        continue;
      }
      if (marker.kind === "terminal") {
        setLatest(watermarks.latestTerminalAt, marker.alias, marker.value);
      } else if (marker.kind === "read") {
        setLatest(watermarks.readThroughAt, marker.alias, marker.value);
      } else {
        watermarks.pendingUnreadBots.add(marker.alias);
      }
    }
  } catch {
    // Return the markers gathered before storage became unavailable.
  }
  return watermarks;
}

function toPublicState(watermarks: StoredWatermarks): ChatUnreadState {
  const aliases = new Set([
    ...Object.keys(watermarks.latestTerminalAt),
    ...watermarks.pendingUnreadBots,
  ]);
  const unreadBots = Array.from(aliases).filter((alias) => (
    watermarks.pendingUnreadBots.has(alias)
    || isLaterTimestamp(
      watermarks.latestTerminalAt[alias] || "",
      watermarks.readThroughAt[alias] || "",
    )
  ));
  return {
    latestTerminalAt: watermarks.latestTerminalAt,
    unreadBots,
  };
}

function storeMarker(accountKey: string, kind: MarkerKind, alias: string, value: string) {
  const normalizedAccountKey = accountKey.trim();
  const normalizedAlias = alias.trim();
  const normalizedValue = value.trim();
  if (!normalizedAccountKey || !normalizedAlias || !normalizedValue) {
    return;
  }
  try {
    localStorage.setItem(
      markerStorageKey(normalizedAccountKey, kind, normalizedAlias, normalizedValue),
      "1",
    );
  } catch {
    // The caller still receives its in-memory fallback state.
  }
}

function clearPendingMarkers(accountKey: string, alias: string) {
  const normalizedAlias = alias.trim();
  if (!normalizedAlias) {
    return;
  }
  const keys: string[] = [];
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key) {
        continue;
      }
      const marker = parseMarker(accountKey, key);
      if (marker?.kind === "pending" && marker.alias === normalizedAlias) {
        keys.push(key);
      }
    }
    keys.forEach((key) => localStorage.removeItem(key));
  } catch {
    // Keep pending markers if storage becomes unavailable.
  }
}

function compactMarkers(accountKey: string, alias: string) {
  const watermarks = readWatermarks(accountKey);
  const latestTerminalAt = watermarks.latestTerminalAt[alias] || "";
  const readThroughAt = watermarks.readThroughAt[alias] || "";
  if (!latestTerminalAt && !readThroughAt) {
    return;
  }
  const keys: string[] = [];
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key) {
        continue;
      }
      const marker = parseMarker(accountKey, key);
      if (
        marker
        && marker.alias === alias
        && (
          (marker.kind === "terminal" && isLaterTimestamp(latestTerminalAt, marker.value))
          || (marker.kind === "read" && isLaterTimestamp(readThroughAt, marker.value))
        )
      ) {
        keys.push(key);
      }
    }
    keys.forEach((key) => localStorage.removeItem(key));
  } catch {
    // Old markers are harmless if compaction cannot run.
  }
}

function isInitialized(accountKey: string) {
  try {
    return localStorage.getItem(initializedStorageKey(accountKey)) === "1";
  } catch {
    return false;
  }
}

function markInitialized(accountKey: string) {
  try {
    localStorage.setItem(initializedStorageKey(accountKey), "1");
  } catch {
    // A later reconciliation can initialize again.
  }
}

function markAliasRead(accountKey: string, alias: string) {
  const watermarks = readWatermarks(accountKey);
  const latest = watermarks.latestTerminalAt[alias] || "";
  if (latest) {
    storeMarker(accountKey, "read", alias, latest);
  }
  clearPendingMarkers(accountKey, alias);
  compactMarkers(accountKey, alias);
}

export function reconcileStoredChatUnread(
  accountKey: string,
  bots: BotCompletion[],
  readBotAlias?: string | null,
): ChatUnreadState {
  const initialized = isInitialized(accountKey);
  for (const bot of bots) {
    const alias = String(bot.alias || "").trim();
    const terminalAt = normalizeTimestamp(bot.lastAnswerTerminalAt || bot.lastAnswerCompletedAt);
    if (!alias || !terminalAt) {
      continue;
    }
    if (!initialized) {
      storeMarker(accountKey, "read", alias, terminalAt);
    }
    storeMarker(accountKey, "terminal", alias, terminalAt);
    compactMarkers(accountKey, alias);
  }
  if (!initialized && bots.length > 0) {
    markInitialized(accountKey);
  }

  const normalizedReadAlias = String(readBotAlias || "").trim();
  if (normalizedReadAlias) {
    markAliasRead(accountKey, normalizedReadAlias);
  }
  return toPublicState(readWatermarks(accountKey));
}

export function recordStoredChatCompletion(
  accountKey: string,
  alias: string,
  terminalAt: string,
  unread: boolean,
): ChatUnreadState {
  const normalizedAlias = alias.trim();
  const normalizedTerminalAt = normalizeTimestamp(terminalAt);
  markInitialized(accountKey);
  if (normalizedTerminalAt) {
    if (!unread) {
      storeMarker(accountKey, "read", normalizedAlias, normalizedTerminalAt);
    }
    storeMarker(accountKey, "terminal", normalizedAlias, normalizedTerminalAt);
    if (!unread) {
      clearPendingMarkers(accountKey, normalizedAlias);
    }
    compactMarkers(accountKey, normalizedAlias);
  } else if (unread) {
    storeMarker(accountKey, "pending", normalizedAlias, "unread");
  } else {
    clearPendingMarkers(accountKey, normalizedAlias);
  }
  const watermarks = readWatermarks(accountKey);
  if (normalizedTerminalAt) {
    setLatest(watermarks.latestTerminalAt, normalizedAlias, normalizedTerminalAt);
    if (!unread) {
      setLatest(watermarks.readThroughAt, normalizedAlias, normalizedTerminalAt);
      watermarks.pendingUnreadBots.delete(normalizedAlias);
    }
  } else if (unread) {
    watermarks.pendingUnreadBots.add(normalizedAlias);
  } else {
    watermarks.pendingUnreadBots.delete(normalizedAlias);
  }
  return toPublicState(watermarks);
}

export function markStoredChatUnread(accountKey: string, alias: string): ChatUnreadState {
  const normalizedAlias = alias.trim();
  markInitialized(accountKey);
  storeMarker(accountKey, "pending", normalizedAlias, "unread");
  const watermarks = readWatermarks(accountKey);
  if (normalizedAlias) {
    watermarks.pendingUnreadBots.add(normalizedAlias);
  }
  return toPublicState(watermarks);
}

export function markStoredChatRead(accountKey: string, alias: string): ChatUnreadState {
  const normalizedAlias = alias.trim();
  markInitialized(accountKey);
  markAliasRead(accountKey, normalizedAlias);
  const watermarks = readWatermarks(accountKey);
  const latest = watermarks.latestTerminalAt[normalizedAlias] || "";
  if (latest) {
    setLatest(watermarks.readThroughAt, normalizedAlias, latest);
  }
  watermarks.pendingUnreadBots.delete(normalizedAlias);
  return toPublicState(watermarks);
}
