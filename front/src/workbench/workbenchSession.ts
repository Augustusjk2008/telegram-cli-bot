import {
  WORKBENCH_CLEAN_TAB_SNAPSHOT_LIMIT_BYTES,
  WORKBENCH_SESSION_VERSION,
  WORKBENCH_SNAPSHOT_TOTAL_LIMIT_BYTES,
  isDesktopSidebarView,
  type PersistedWorkbenchSession,
  type PersistedWorkbenchTab,
} from "./workbenchTypes";

function byteSize(value: string) {
  return new Blob([value]).size;
}

function normalizeTab(raw: unknown): PersistedWorkbenchTab | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const candidate = raw as Record<string, unknown>;
  const path = typeof candidate.path === "string" ? candidate.path.trim() : "";
  if (!path) {
    return null;
  }

  const dirty = candidate.dirty === true;
  const rawDocumentVersion = Number(candidate.documentVersion);
  const documentVersion = Number.isFinite(rawDocumentVersion) && rawDocumentVersion >= 1
    ? Math.max(1, Math.trunc(rawDocumentVersion))
    : undefined;
  const savedContent = typeof candidate.savedContent === "string" ? candidate.savedContent : undefined;
  const draftContent = typeof candidate.draftContent === "string" ? candidate.draftContent : undefined;
  const encoding = typeof candidate.encoding === "string" ? candidate.encoding : undefined;
  const contentPersistence = candidate.contentPersistence;

  let normalizedPersistence: PersistedWorkbenchTab["contentPersistence"] = "none";
  if (dirty && draftContent !== undefined) {
    normalizedPersistence = "dirty_snapshot";
  } else if (
    !dirty
    && savedContent !== undefined
    && contentPersistence === "clean_snapshot"
    && byteSize(savedContent) <= WORKBENCH_CLEAN_TAB_SNAPSHOT_LIMIT_BYTES
  ) {
    normalizedPersistence = "clean_snapshot";
  }

  return {
    path,
    dirty,
    documentVersion,
    lastModifiedNs: typeof candidate.lastModifiedNs === "string" ? candidate.lastModifiedNs : undefined,
    encoding,
    savedContent: normalizedPersistence === "clean_snapshot" ? savedContent : undefined,
    draftContent: normalizedPersistence === "dirty_snapshot" ? draftContent : undefined,
    contentPersistence: normalizedPersistence,
  };
}

export function buildWorkbenchSessionStorageKey(botAlias: string, workspaceRoot: string, accountId?: string) {
  const accountScope = accountId?.trim();
  const prefix = accountScope ? `${accountScope}:` : "";
  return `web-workbench-session:v1:${prefix}${botAlias}:${encodeURIComponent(workspaceRoot)}`;
}

export function selectTabsForPersistence(
  tabs: Array<{
    path: string;
    dirty: boolean;
    documentVersion?: number;
    savedContent: string;
    draftContent?: string;
    lastModifiedNs?: string;
    encoding?: string;
  }>,
): PersistedWorkbenchTab[] {
  const selected: PersistedWorkbenchTab[] = [];
  let totalBytes = 0;

  for (const tab of tabs) {
    const draftContent = tab.dirty ? tab.draftContent ?? tab.savedContent : undefined;
    const savedContent = !tab.dirty ? tab.savedContent : undefined;
    const nextSize = byteSize(draftContent ?? savedContent ?? "");
    const canKeepClean = !tab.dirty && nextSize <= WORKBENCH_CLEAN_TAB_SNAPSHOT_LIMIT_BYTES;
    const canKeepAny = totalBytes + nextSize <= WORKBENCH_SNAPSHOT_TOTAL_LIMIT_BYTES;

    const persisted: PersistedWorkbenchTab = {
      path: tab.path,
      dirty: tab.dirty,
      documentVersion: tab.documentVersion,
      lastModifiedNs: tab.lastModifiedNs,
      encoding: tab.encoding,
      savedContent: undefined,
      draftContent: undefined,
      contentPersistence: "none",
    };

    if (tab.dirty && draftContent && canKeepAny) {
      persisted.draftContent = draftContent;
      persisted.contentPersistence = "dirty_snapshot";
      totalBytes += nextSize;
    } else if (!tab.dirty && savedContent && canKeepClean && canKeepAny) {
      persisted.savedContent = savedContent;
      persisted.contentPersistence = "clean_snapshot";
      totalBytes += nextSize;
    }

    selected.push(persisted);
  }

  return selected;
}

export function normalizePersistedWorkbenchSession(raw: unknown): PersistedWorkbenchSession | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const candidate = raw as Record<string, unknown>;
  if (candidate.version !== WORKBENCH_SESSION_VERSION) {
    return null;
  }

  const botAlias = typeof candidate.botAlias === "string" ? candidate.botAlias.trim() : "";
  const workspaceRoot = typeof candidate.workspaceRoot === "string" ? candidate.workspaceRoot.trim() : "";
  const sidebarView = isDesktopSidebarView(candidate.sidebarView) ? candidate.sidebarView : "files";
  if (!botAlias || !workspaceRoot) {
    return null;
  }

  return {
    version: WORKBENCH_SESSION_VERSION,
    botAlias,
    workspaceRoot,
    sidebarView,
    expandedPaths: Array.isArray(candidate.expandedPaths)
      ? candidate.expandedPaths.filter((item): item is string => typeof item === "string" && item.length > 0)
      : [],
    selectedTreePath: typeof candidate.selectedTreePath === "string"
      ? candidate.selectedTreePath.trim()
      : undefined,
    activeTabPath: typeof candidate.activeTabPath === "string" ? candidate.activeTabPath : "",
    terminalOverrideCwd: typeof candidate.terminalOverrideCwd === "string" ? candidate.terminalOverrideCwd : undefined,
    focusedPane:
      candidate.focusedPane === "sidebar"
      || candidate.focusedPane === "editor"
      || candidate.focusedPane === "terminal"
      || candidate.focusedPane === "chat"
        ? candidate.focusedPane
        : null,
    tabs: Array.isArray(candidate.tabs)
      ? candidate.tabs.map(normalizeTab).filter((item): item is PersistedWorkbenchTab => item !== null)
      : [],
  };
}

export function readWorkbenchSession(botAlias: string, workspaceRoot: string, accountId?: string): PersistedWorkbenchSession | null {
  try {
    const raw = localStorage.getItem(buildWorkbenchSessionStorageKey(botAlias, workspaceRoot, accountId));
    return raw ? normalizePersistedWorkbenchSession(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

export function writeWorkbenchSession(session: PersistedWorkbenchSession, accountId?: string) {
  localStorage.setItem(
    buildWorkbenchSessionStorageKey(session.botAlias, session.workspaceRoot, accountId),
    JSON.stringify(session),
  );
}
