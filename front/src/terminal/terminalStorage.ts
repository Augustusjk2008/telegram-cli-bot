const TERMINAL_OWNER_STORAGE_KEY = "web-terminal-owner-id";
const TERMINAL_TABS_STORAGE_KEY = "web-terminal-tabs:v1";
const INVALID_TERMINAL_OWNER_IDS = new Set(["null", "undefined"]);

export type StoredTerminalTab = {
  id: string;
  ownerId: string;
  title: string;
  cwd: string;
  shell: string;
};

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

function normalizeStoredTab(value: unknown, index: number): StoredTerminalTab | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  const ownerId = typeof candidate.ownerId === "string"
    ? candidate.ownerId.trim()
    : typeof candidate.owner_id === "string"
      ? candidate.owner_id.trim()
      : "";
  if (!isValidTerminalOwnerId(ownerId)) {
    return null;
  }
  const id = typeof candidate.id === "string" && candidate.id.trim()
    ? candidate.id.trim()
    : ownerId;
  const title = typeof candidate.title === "string" && candidate.title.trim()
    ? candidate.title.trim()
    : `终端 ${index + 1}`;
  const cwd = typeof candidate.cwd === "string" ? candidate.cwd.trim() : "";
  const shell = typeof candidate.shell === "string" && candidate.shell.trim()
    ? candidate.shell.trim()
    : "auto";
  return { id, ownerId, title, cwd, shell };
}

export function createStoredTerminalTab(
  tabs: StoredTerminalTab[] = [],
  options: { title?: string; cwd?: string; shell?: string } = {},
): StoredTerminalTab {
  const ownerId = createTerminalOwnerId();
  let title = options.title?.trim() || "";
  if (!title) {
    let index = tabs.length + 1;
    const usedTitles = new Set(tabs.map((tab) => tab.title));
    while (usedTitles.has(`终端 ${index}`)) {
      index += 1;
    }
    title = `终端 ${index}`;
  }
  return {
    id: ownerId,
    ownerId,
    title,
    cwd: options.cwd?.trim() || "",
    shell: options.shell?.trim() || "auto",
  };
}

export function readTerminalTabs(): StoredTerminalTab[] {
  if (typeof localStorage === "undefined") {
    return [createStoredTerminalTab()];
  }
  try {
    const raw = localStorage.getItem(TERMINAL_TABS_STORAGE_KEY);
    if (raw !== null) {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed)
        ? parsed.map((item, index) => normalizeStoredTab(item, index)).filter((item): item is StoredTerminalTab => item !== null)
        : [];
    }
    const legacyOwnerId = localStorage.getItem(TERMINAL_OWNER_STORAGE_KEY);
    const migrated = isValidTerminalOwnerId(legacyOwnerId)
      ? [{ id: legacyOwnerId!.trim(), ownerId: legacyOwnerId!.trim(), title: "终端 1", cwd: "", shell: "auto" }]
      : [createStoredTerminalTab()];
    localStorage.setItem(TERMINAL_TABS_STORAGE_KEY, JSON.stringify(migrated));
    return migrated;
  } catch {
    return [createStoredTerminalTab()];
  }
}

export function writeTerminalTabs(tabs: StoredTerminalTab[]) {
  if (typeof localStorage === "undefined") {
    return;
  }
  try {
    localStorage.setItem(TERMINAL_TABS_STORAGE_KEY, JSON.stringify(tabs));
  } catch {
    // Storage can be unavailable in private browsing; runtime state still works.
  }
}

export function readTerminalOwnerId() {
  return readTerminalTabs()[0]?.ownerId || createTerminalOwnerId();
}
