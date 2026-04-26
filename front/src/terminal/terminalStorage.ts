const TERMINAL_OWNER_STORAGE_KEY = "web-terminal-owner-id";
const INVALID_TERMINAL_OWNER_IDS = new Set(["null", "undefined"]);

function createTerminalOwnerId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `terminal-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isValidTerminalOwnerId(value: string | null) {
  if (!value) {
    return false;
  }
  const ownerId = value.trim();
  return ownerId.length > 0 && !INVALID_TERMINAL_OWNER_IDS.has(ownerId);
}

export function readTerminalOwnerId() {
  if (typeof localStorage === "undefined") {
    return createTerminalOwnerId();
  }
  try {
    const existing = localStorage.getItem(TERMINAL_OWNER_STORAGE_KEY);
    if (isValidTerminalOwnerId(existing)) {
      return existing.trim();
    }
    const created = createTerminalOwnerId();
    localStorage.setItem(TERMINAL_OWNER_STORAGE_KEY, created);
    return created;
  } catch {
    return createTerminalOwnerId();
  }
}
