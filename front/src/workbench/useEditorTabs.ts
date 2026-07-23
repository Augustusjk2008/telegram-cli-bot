import { useEffect, useRef, useState } from "react";
import { inferFileEditorLanguageId } from "../utils/fileEditorLanguage";
import type {
  PluginOpenTarget,
  WorkspaceDocumentCloseInput,
  CodeNavigationDocumentSyncEvent,
  WorkspaceDocumentSyncInput,
  CodeNavigationDocumentSyncItem,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { selectTabsForPersistence } from "./workbenchSession";
import {
  CLOSED_TAB_HISTORY_LIMIT,
  type EditorTab,
  type PersistedWorkbenchTab,
  type PersistedWorkbenchSession,
} from "./workbenchTypes";

type Props = {
  botAlias: string;
  client: WebBotClient;
  scopeKey?: string;
  structureOnly?: boolean;
  canWriteFiles?: boolean;
};

export const EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS = 250;
export const EDITOR_DOCUMENT_MAX_BYTES = 512 * 1024;
export const EDITOR_DOCUMENT_BATCH_MAX_BYTES = 2 * 1024 * 1024;
const EDITOR_DOCUMENT_BATCH_MAX_COUNT = 64;

function documentByteSize(content: string) {
  return new Blob([content]).size;
}

function isSyncableTab(tab: EditorTab | null | undefined): tab is EditorTab {
  return Boolean(tab && tab.kind === "file" && tab.path && !tab.cold && !tab.missing);
}

function toSyncItem(tab: EditorTab): CodeNavigationDocumentSyncItem {
  return {
    path: tab.path,
    languageId: inferFileEditorLanguageId(tab.path),
    version: Math.max(1, Math.trunc(tab.documentVersion || 1)),
    content: tab.content,
  };
}

function basename(path: string) {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function clonePluginTargets(pluginTargets?: PluginOpenTarget[]) {
  return pluginTargets?.map((target) => ({
    ...target,
    input: { ...target.input },
  }));
}

function createTab(
  path: string,
  content: string,
  lastModifiedNs?: string,
  overrides?: Partial<EditorTab>,
): EditorTab {
  return {
    path,
    basename: basename(path),
    content,
    documentVersion: Math.max(1, Math.trunc(Number(overrides?.documentVersion) || 1)),
    savedContent: content,
    dirty: false,
    loading: false,
    saving: false,
    statusText: "",
    error: "",
    lastModifiedNs,
    encoding: overrides?.encoding,
    cold: false,
    missing: false,
    kind: "file",
    contentPersistence: "none",
    ...overrides,
  };
}

function createTabFromSnapshot(tab: PersistedWorkbenchTab): EditorTab {
  if (tab.contentPersistence === "dirty_snapshot") {
    const draftContent = tab.draftContent ?? tab.savedContent ?? "";
    return createTab(tab.path, draftContent, tab.lastModifiedNs, {
      savedContent: tab.savedContent ?? "",
      dirty: true,
      documentVersion: tab.documentVersion,
      contentPersistence: "dirty_snapshot",
      encoding: tab.encoding,
    });
  }

  if (tab.contentPersistence === "clean_snapshot") {
    const savedContent = tab.savedContent ?? "";
    return createTab(tab.path, savedContent, tab.lastModifiedNs, {
      documentVersion: tab.documentVersion,
      contentPersistence: "clean_snapshot",
      encoding: tab.encoding,
    });
  }

  return createTab(tab.path, "", tab.lastModifiedNs, {
    documentVersion: tab.documentVersion,
    cold: true,
    contentPersistence: "none",
    encoding: tab.encoding,
  });
}

export function useEditorTabs({ botAlias, client, scopeKey = "", structureOnly = false, canWriteFiles = true }: Props) {
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTabPath, setActiveTabPath] = useState("");
  const [closedTabs, setClosedTabs] = useState<PersistedWorkbenchTab[]>([]);
  const tabsRef = useRef<EditorTab[]>([]);
  const activeTabPathRef = useRef("");
  const closedTabsRef = useRef<PersistedWorkbenchTab[]>([]);
  const scopeIdentity = `${botAlias}\n${scopeKey}`;
  const documentSyncTimersRef = useRef<Map<string, number>>(new Map());
  const pendingDocumentSyncRef = useRef<Map<string, { item: CodeNavigationDocumentSyncItem; event: CodeNavigationDocumentSyncEvent }>>(new Map());
  const documentSyncAbortRef = useRef<AbortController | null>(null);
  const lastReplayClientRef = useRef<WebBotClient | null>(null);
  const lastReplayScopeRef = useRef(scopeIdentity);
  const scopeIdentityRef = useRef(scopeIdentity);
  const scopeClientRef = useRef(client);
  const scopeGenerationRef = useRef(0);
  if (scopeIdentityRef.current !== scopeIdentity || scopeClientRef.current !== client) {
    scopeIdentityRef.current = scopeIdentity;
    scopeClientRef.current = client;
    scopeGenerationRef.current += 1;
  }

  function isCurrentScope(generation: number) {
    return scopeGenerationRef.current === generation;
  }

  function setDocumentSyncError(paths: string[], message: string) {
    if (paths.length === 0) {
      return;
    }
    const pathSet = new Set(paths);
    setTabs((current) => current.map((tab) => pathSet.has(tab.path)
      ? { ...tab, error: message, statusText: "语言服务同步失败" }
      : tab));
  }

  function clearDocumentSyncTimer(path: string) {
    const timer = documentSyncTimersRef.current.get(path);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      documentSyncTimersRef.current.delete(path);
    }
  }

  function queueDocumentSync(tab: EditorTab, event: CodeNavigationDocumentSyncEvent = "didChange") {
    if (!isSyncableTab(tab)) {
      return;
    }
    if (documentByteSize(tab.content) > EDITOR_DOCUMENT_MAX_BYTES) {
      setDocumentSyncError([tab.path], "文件内容超过语言服务同步限制（512 KB）");
      return;
    }
    pendingDocumentSyncRef.current.set(tab.path, { item: toSyncItem(tab), event });
    clearDocumentSyncTimer(tab.path);
    const timer = window.setTimeout(() => {
      documentSyncTimersRef.current.delete(tab.path);
      void flushDocumentSync();
    }, EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS);
    documentSyncTimersRef.current.set(tab.path, timer);
  }

  function abortDocumentSync() {
    documentSyncAbortRef.current?.abort();
    documentSyncAbortRef.current = null;
  }

  async function sendDocumentSync(items: CodeNavigationDocumentSyncItem[], event: CodeNavigationDocumentSyncEvent) {
    if (items.length === 0) {
      return;
    }
    const controller = typeof AbortController === "undefined" ? null : new AbortController();
    abortDocumentSync();
    documentSyncAbortRef.current = controller;
    const input: WorkspaceDocumentSyncInput = { documents: items, event };
    try {
      await client.syncWorkspaceDocuments(botAlias, input, controller?.signal);
    } catch (error) {
      if (!controller?.signal.aborted) {
        setDocumentSyncError(items.map((item) => item.path), error instanceof Error ? error.message : "语言服务同步失败");
      }
    } finally {
      if (documentSyncAbortRef.current === controller) {
        documentSyncAbortRef.current = null;
      }
    }
  }

  async function flushDocumentSync() {
    const pending = Array.from(pendingDocumentSyncRef.current.values());
    pendingDocumentSyncRef.current.clear();
    if (pending.length === 0) {
      return;
    }
    const chunks: Array<{ items: CodeNavigationDocumentSyncItem[]; event: CodeNavigationDocumentSyncEvent }> = [];
    let current: CodeNavigationDocumentSyncItem[] = [];
    let currentBytes = 0;
    let currentEvent: CodeNavigationDocumentSyncEvent = pending[0]?.event || "didChange";
    for (const entry of pending) {
      const size = documentByteSize(entry.item.content || "");
      if (current.length > 0 && (currentBytes + size > EDITOR_DOCUMENT_BATCH_MAX_BYTES || current.length >= EDITOR_DOCUMENT_BATCH_MAX_COUNT)) {
        chunks.push({ items: current, event: currentEvent });
        current = [];
        currentBytes = 0;
        currentEvent = entry.event;
      }
      current.push(entry.item);
      currentBytes += size;
      if (entry.event === "didOpen") {
        currentEvent = "didOpen";
      }
    }
    if (current.length > 0) {
      chunks.push({ items: current, event: currentEvent });
    }
    for (const chunk of chunks) {
      await sendDocumentSync(chunk.items, chunk.event);
    }
  }

  async function closeDocuments(tabsToClose: EditorTab[]) {
    const documents = tabsToClose.filter(isSyncableTab).map<WorkspaceDocumentCloseInput["documents"][number]>((tab) => ({
      path: tab.path,
      version: Math.max(1, Math.trunc(tab.documentVersion || 1)),
    }));
    if (documents.length === 0) {
      return;
    }
    abortDocumentSync();
    documents.forEach((document) => {
      clearDocumentSyncTimer(document.path);
      pendingDocumentSyncRef.current.delete(document.path);
    });
    try {
      await client.closeWorkspaceDocuments(botAlias, { documents });
    } catch {
      // Closing is best effort; scope changes must not block the editor.
    }
  }

  useEffect(() => {
    tabsRef.current = tabs;
  }, [tabs]);

  useEffect(() => {
    activeTabPathRef.current = activeTabPath;
  }, [activeTabPath]);

  useEffect(() => {
    closedTabsRef.current = closedTabs;
  }, [closedTabs]);

  function disposePluginSession(tab?: EditorTab | null) {
    const pluginView = tab?.pluginView;
    if (!pluginView || pluginView.mode !== "session") {
      return;
    }
    void client.disposePluginViewSession(botAlias, pluginView.pluginId, pluginView.sessionId).catch(() => {});
  }

  useEffect(() => () => {
    abortDocumentSync();
    void closeDocuments(tabsRef.current);
    tabsRef.current.forEach((tab) => disposePluginSession(tab));
  }, [scopeIdentity]);

  useEffect(() => {
    setTabs([]);
    setActiveTabPath("");
    setClosedTabs([]);
  }, [scopeIdentity]);

  useEffect(() => {
    if (lastReplayScopeRef.current !== scopeIdentity) {
      lastReplayScopeRef.current = scopeIdentity;
      lastReplayClientRef.current = client;
      return;
    }
    if (lastReplayClientRef.current === client) {
      return;
    }
    lastReplayClientRef.current = client;
    const replay = tabsRef.current.filter(isSyncableTab);
    replay.forEach((tab) => queueDocumentSync(tab, "didOpen"));
    if (replay.length > 0) {
      void flushDocumentSync();
    }
  }, [client, scopeIdentity]);

  const activeTab = tabs.find((tab) => tab.path === activeTabPath) || null;
  const hasDirtyTabs = tabs.some((tab) => tab.dirty);

  function pushClosedTab(path: string) {
    const target = tabsRef.current.find((item) => item.path === path);
    if (!target) {
      return;
    }
    if (target.kind === "git-diff" || target.readOnly) {
      return;
    }

    const nextClosedTab: PersistedWorkbenchTab = {
      path: target.path,
      dirty: target.dirty,
      documentVersion: target.documentVersion,
      lastModifiedNs: target.lastModifiedNs,
      encoding: target.encoding,
      savedContent: target.savedContent,
      draftContent: target.content,
      contentPersistence: target.dirty ? "dirty_snapshot" : "clean_snapshot",
    };

    setClosedTabs((current) => [
      nextClosedTab,
      ...current.filter((item) => item.path !== path),
    ].slice(0, CLOSED_TAB_HISTORY_LIMIT));
  }

  async function hydrateTabContent(path: string, generation = scopeGenerationRef.current) {
    if (structureOnly || !isCurrentScope(generation)) {
      return;
    }
    const target = tabsRef.current.find((item) => item.path === path);
    if (target && !target.cold && !target.missing) {
      return;
    }

    setTabs((current) => isCurrentScope(generation) && current.some((item) => item.path === path)
      ? current.map((item) => item.path === path
        ? {
            ...item,
            loading: true,
            error: "",
            statusText: "",
          }
        : item)
      : current);

    try {
      const result = await client.readFileFull(botAlias, path);
      if (!isCurrentScope(generation)) {
        return;
      }
      setTabs((current) => isCurrentScope(generation) && current.some((item) => item.path === path)
        ? current.map((item) => item.path === path
          ? {
              ...item,
              basename: basename(path),
              content: result.content || "",
              savedContent: result.content || "",
              documentVersion: Math.max(1, Math.trunc(target?.documentVersion || 1)),
              dirty: false,
              loading: false,
              saving: false,
              error: "",
              statusText: "",
              lastModifiedNs: result.lastModifiedNs,
              encoding: result.encoding,
              cold: false,
              missing: false,
              readOnly: !canWriteFiles,
              contentPersistence: "none",
            }
          : item)
        : current);
      const synced = tabsRef.current.find((item) => item.path === path);
      if (synced) {
        queueDocumentSync({
          ...synced,
          content: result.content || "",
          savedContent: result.content || "",
          cold: false,
          missing: false,
        }, "didOpen");
      }
    } catch (error) {
      if (!isCurrentScope(generation)) {
        return;
      }
      const message = error instanceof Error ? error.message : "读取文件失败";
      setTabs((current) => isCurrentScope(generation) && current.some((item) => item.path === path)
        ? current.map((item) => item.path === path
          ? {
              ...item,
              loading: false,
              error: message,
              statusText: "",
              cold: false,
              missing: true,
            }
          : item)
        : current);
    }
  }

  function openCreatedFile(path: string, content: string, lastModifiedNs?: string) {
    if (structureOnly || !canWriteFiles) {
      return;
    }
    const nextTab = createTab(path, content, lastModifiedNs, { contentPersistence: "none" });
    const currentTabs = tabsRef.current;
    const existingIndex = currentTabs.findIndex((item) => item.path === path);
    const nextTabs = existingIndex >= 0 ? currentTabs.slice() : [...currentTabs, nextTab];
    if (existingIndex >= 0) {
      nextTabs[existingIndex] = nextTab;
    }
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    activeTabPathRef.current = path;
    setActiveTabPath(path);
    queueDocumentSync(nextTab, "didOpen");
  }

  async function openFile(path: string, pluginTargets?: PluginOpenTarget[]) {
    if (structureOnly) {
      return;
    }
    const generation = scopeGenerationRef.current;
    const nextPluginTargets = clonePluginTargets(pluginTargets);
    const existing = tabsRef.current.find((item) => item.path === path);
    if (existing) {
      setTabs((current) => current.map((item) => item.path === path
        ? {
            ...item,
            pluginTargets: nextPluginTargets,
          }
        : item));
      setActiveTabPath(path);
      if (existing.cold || existing.missing) {
        await hydrateTabContent(path, generation);
      }
      return;
    }

    setTabs((current) => [
      ...current,
      createTab(path, "", undefined, {
        loading: true,
        cold: true,
        readOnly: !canWriteFiles,
        pluginTargets: nextPluginTargets,
      }),
    ]);
    setActiveTabPath(path);
    await hydrateTabContent(path, generation);
  }

  async function openPluginView(target: PluginOpenTarget) {
    const sourcePath = typeof target.input.path === "string" ? target.input.path : undefined;
    const tabPath = `plugin://${target.pluginId}/${target.viewId}/${sourcePath || target.title}`;
    const existing = tabsRef.current.find((item) => item.path === tabPath);
    if (!existing) {
      setTabs((current) => [
        ...current,
        createTab(tabPath, "", undefined, {
          basename: target.title,
          kind: "plugin-view",
          sourcePath,
          readOnly: true,
          statusText: "插件视图",
          loading: true,
          contentPersistence: "none",
        }),
      ]);
    }
    setActiveTabPath(tabPath);

    try {
      const view = await client.openPluginView(botAlias, target.pluginId, target.viewId, target.input);
      const nextTab = createTab(tabPath, "", undefined, {
        basename: target.title,
        kind: "plugin-view",
        pluginView: view,
        pluginInput: { ...target.input },
        sourcePath,
        readOnly: true,
        statusText: "插件视图",
        loading: false,
        contentPersistence: "none",
      });
      if (
        existing?.pluginView?.mode === "session"
        && (view.mode !== "session" || existing.pluginView.sessionId !== view.sessionId)
      ) {
        void client.disposePluginViewSession(botAlias, existing.pluginView.pluginId, existing.pluginView.sessionId).catch(() => {});
      }
      setTabs((current) => {
        const existingIndex = current.findIndex((item) => item.path === tabPath);
        if (existingIndex >= 0) {
          const next = current.slice();
          next[existingIndex] = nextTab;
          return next;
        }
        return [...current, nextTab];
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "打开插件视图失败";
      setTabs((current) => current.map((item) => item.path === tabPath
          ? {
              ...item,
              basename: target.title,
              kind: "plugin-view",
              pluginInput: { ...target.input },
              sourcePath,
              readOnly: true,
              loading: false,
              error: message,
            statusText: "插件视图",
          }
        : item));
    }
  }

  function openReadOnlyTab(input: {
    path: string;
    basename: string;
    content: string;
    statusText?: string;
    sourcePath?: string;
    kind?: EditorTab["kind"];
  }) {
    const nextTab = createTab(input.path, input.content, undefined, {
      basename: input.basename,
      kind: input.kind || "git-diff",
      sourcePath: input.sourcePath,
      readOnly: true,
      statusText: input.statusText || "只读",
      contentPersistence: "none",
    });
    setTabs((current) => {
      const existingIndex = current.findIndex((item) => item.path === input.path);
      if (existingIndex >= 0) {
        const next = current.slice();
        next[existingIndex] = nextTab;
        return next;
      }
      return [...current, nextTab];
    });
    setActiveTabPath(input.path);
  }

  async function activateTab(path: string) {
    setActiveTabPath(path);
    if (structureOnly) {
      return;
    }
    const target = tabsRef.current.find((item) => item.path === path);
    if (target?.cold || target?.missing) {
      await hydrateTabContent(path);
    }
  }

  function updateActiveContent(content: string) {
    const activePath = activeTabPathRef.current;
    const target = tabsRef.current.find((item) => item.path === activePath);
    if (!target || target.readOnly || !canWriteFiles || target.content === content) {
      return;
    }
    const next = {
      ...target,
      content,
      documentVersion: Math.max(1, Math.trunc(target.documentVersion || 1)) + 1,
      dirty: content !== target.savedContent,
      statusText: "",
      error: "",
      missing: false,
    };
    const nextTabs = tabsRef.current.map((item) => item.path === activePath ? next : item);
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    queueDocumentSync(next, "didChange");
  }

  async function saveActiveTab() {
    const currentActivePath = activeTabPathRef.current;
    const target = tabsRef.current.find((item) => item.path === currentActivePath);
    if (!target) {
      return;
    }
    if (target.readOnly) {
      return;
    }
    if (!canWriteFiles) {
      setTabs((current) => current.map((item) => item.path === target.path
        ? { ...item, saving: false, error: "无文件写入权限", statusText: "" }
        : item));
      return;
    }

    setTabs((current) => current.map((item) => item.path === target.path
      ? { ...item, saving: true, error: "", statusText: "" }
      : item));

    try {
      const result = await client.writeFile(botAlias, target.path, target.content, target.lastModifiedNs, target.encoding);
      setTabs((current) => current.map((item) => item.path === target.path
        ? {
            ...item,
            saving: false,
            dirty: false,
            savedContent: item.content,
            statusText: "已保存",
            error: "",
            lastModifiedNs: result.lastModifiedNs,
            encoding: result.encoding || target.encoding,
            contentPersistence: "clean_snapshot",
            cold: false,
            missing: false,
          }
        : item));
    } catch (error) {
      const message = error instanceof Error ? error.message : "保存失败";
      setTabs((current) => current.map((item) => item.path === target.path
        ? { ...item, saving: false, error: message }
        : item));
    }
  }

  function closePath(path: string) {
    const target = tabsRef.current.find((item) => item.path === path);
    if (target) {
      void closeDocuments([target]);
      disposePluginSession(target);
    }
    setTabs((current) => {
      const index = current.findIndex((item) => item.path === path);
      if (index < 0) {
        return current;
      }
      const nextTabs = current.filter((item) => item.path !== path);
      if (activeTabPathRef.current !== path) {
        return nextTabs;
      }
      const nextActive = nextTabs[Math.max(0, index - 1)]?.path || nextTabs[nextTabs.length - 1]?.path || "";
      setActiveTabPath(nextActive);
      return nextTabs;
    });
  }

  function closeTab(path: string) {
    const target = tabsRef.current.find((item) => item.path === path);
    if (!target) {
      return true;
    }
    if (target.dirty && !window.confirm("文件尚未保存，确定放弃修改吗？")) {
      return false;
    }
    pushClosedTab(path);
    closePath(path);
    return true;
  }

  function closeOtherTabs(path: string) {
    const nextClosed = tabsRef.current.filter((item) => item.path !== path);
    nextClosed.forEach((item) => pushClosedTab(item.path));
    nextClosed.forEach((item) => disposePluginSession(item));
    void closeDocuments(nextClosed);
    setTabs((current) => current.filter((item) => item.path === path));
    setActiveTabPath(path);
  }

  function closeTabsToRight(path: string) {
    const index = tabsRef.current.findIndex((item) => item.path === path);
    if (index < 0) {
      return;
    }
    tabsRef.current.slice(index + 1).forEach((item) => {
      pushClosedTab(item.path);
      disposePluginSession(item);
    });
    void closeDocuments(tabsRef.current.slice(index + 1));
    setTabs((current) => current.slice(0, index + 1));
  }

  async function reopenLastClosedTab() {
    if (structureOnly || !canWriteFiles) {
      return;
    }
    const target = closedTabsRef.current[0];
    if (!target) {
      return;
    }
    setClosedTabs((current) => current.slice(1));
    await restoreFromSnapshot([target], target.path, { append: true });
  }

  function syncRenamedPath(oldPath: string, nextPath: string) {
    setTabs((current) => current.map((item) => item.path === oldPath
      ? {
          ...item,
          path: nextPath,
          basename: basename(nextPath),
        }
      : item));
    setActiveTabPath((current) => current === oldPath ? nextPath : current);
    setClosedTabs((current) => current.map((item) => item.path === oldPath
      ? { ...item, path: nextPath }
      : item));
  }

  async function restoreFromSnapshot(
    restoredTabs: PersistedWorkbenchSession["tabs"],
    restoredActiveTabPath: string,
    options?: { append?: boolean },
  ) {
    if (structureOnly || !canWriteFiles) {
      if (!options?.append) {
        setTabs([]);
        setActiveTabPath("");
      }
      return;
    }
    const snapshotTabs = restoredTabs.map(createTabFromSnapshot);
    if (snapshotTabs.length === 0) {
      if (!options?.append) {
        setTabs([]);
        setActiveTabPath("");
      }
      return;
    }

    const nextActiveTabPath = snapshotTabs.some((item) => item.path === restoredActiveTabPath)
      ? restoredActiveTabPath
      : snapshotTabs[0]?.path || "";

    if (options?.append) {
      setTabs((current) => {
        const merged = [...current];
        for (const tab of snapshotTabs) {
          if (merged.some((item) => item.path === tab.path)) {
            continue;
          }
          merged.push(tab);
        }
        return merged;
      });
    } else {
      setTabs(snapshotTabs);
    }
    setActiveTabPath(nextActiveTabPath);
    snapshotTabs.filter(isSyncableTab).forEach((tab) => queueDocumentSync(tab, "didOpen"));

    const activeRestoredTab = snapshotTabs.find((item) => item.path === nextActiveTabPath);
    if (activeRestoredTab?.cold) {
      await hydrateTabContent(activeRestoredTab.path);
    }
  }

  function buildPersistenceSnapshot() {
    return selectTabsForPersistence(
      tabsRef.current.map((tab) => ({
        kind: tab.kind,
        path: tab.path,
        dirty: tab.dirty,
        savedContent: tab.savedContent,
        draftContent: tab.content,
        documentVersion: tab.documentVersion,
        lastModifiedNs: tab.lastModifiedNs,
        encoding: tab.encoding,
      })).filter((tab) => tab.kind !== "git-diff" && tab.kind !== "plugin-view"),
    );
  }

  return {
    tabs,
    activeTab,
    activeTabPath,
    hasDirtyTabs,
    closedTabs,
    openFile,
    openPluginView,
    openReadOnlyTab,
    openCreatedFile,
    restoreFromSnapshot,
    buildPersistenceSnapshot,
    activateTab,
    updateActiveContent,
    saveActiveTab,
    closeTab,
    closePath,
    closeOtherTabs,
    closeTabsToRight,
    reopenLastClosedTab,
    syncRenamedPath,
  };
}
