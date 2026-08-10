import { useEffect, useRef, useState } from "react";
import { inferFileEditorLanguageId } from "../utils/fileEditorLanguage";
import { getExternalSourceErrorMessage } from "../services/types";
import type {
  ExternalSourceReadResult,
  FileReadResult,
  PluginOpenTarget,
  PluginRenderResult,
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
  return parts[parts.length - 1]?.trim() || path.trim();
}

function externalTabPath(sourceId: string) {
  return `external-source:${sourceId}`;
}

function filePreviewTabPath(path: string) {
  return `file-preview:${path}`;
}

function normalizeEditorSourcePath(path: string) {
  return path.trim().replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/$/, "");
}

function isSameOrDescendantSourcePath(path: string, parentPath: string) {
  const normalizedPath = normalizeEditorSourcePath(path);
  const normalizedParent = normalizeEditorSourcePath(parentPath);
  return Boolean(
    normalizedPath
    && normalizedParent
    && (normalizedPath === normalizedParent || normalizedPath.startsWith(`${normalizedParent}/`)),
  );
}

function remapEditorSourcePath(path: string, oldPath: string, nextPath: string) {
  const normalizedPath = normalizeEditorSourcePath(path);
  const normalizedOldPath = normalizeEditorSourcePath(oldPath);
  const normalizedNextPath = normalizeEditorSourcePath(nextPath);
  if (!normalizedPath || !normalizedOldPath || !normalizedNextPath) {
    return path;
  }
  if (normalizedPath === normalizedOldPath) {
    return normalizedNextPath;
  }
  if (!normalizedPath.startsWith(`${normalizedOldPath}/`)) {
    return path;
  }
  return `${normalizedNextPath}${normalizedPath.slice(normalizedOldPath.length)}`;
}

function editorTabSourcePath(tab: EditorTab) {
  if (tab.kind === "file") {
    return tab.path;
  }
  if (tab.kind === "file-preview" || tab.kind === "plugin-view" || tab.kind === "git-diff") {
    return tab.sourcePath || "";
  }
  return "";
}

function externalDisplayName(displayPath: string, sourceId: string) {
  const normalized = String(displayPath || "").trim();
  return basename(normalized) || (sourceId ? "外部源码" : "外部依赖");
}

function clonePluginTargets(pluginTargets?: PluginOpenTarget[]) {
  return pluginTargets?.map((target) => ({
    ...target,
    input: { ...target.input },
  }));
}

function clonePluginTarget(target: PluginOpenTarget): PluginOpenTarget {
  return {
    ...target,
    input: { ...target.input },
  };
}

function pluginViewTabPath(target: PluginOpenTarget) {
  const sourcePath = typeof target.input.path === "string" ? target.input.path : "";
  return `plugin://${target.pluginId}/${target.viewId}/${sourcePath || target.title}`;
}

function remapPluginTarget(target: PluginOpenTarget, oldPath: string, nextPath: string) {
  const sourcePath = typeof target.input.path === "string" ? target.input.path : "";
  const nextSourcePath = sourcePath ? remapEditorSourcePath(sourcePath, oldPath, nextPath) : sourcePath;
  return nextSourcePath && nextSourcePath !== sourcePath
    ? { ...target, input: { ...target.input, path: nextSourcePath } }
    : target;
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
  const pluginViewRequestSerialRef = useRef(0);
  const pluginViewRequestSeqRef = useRef(new Map<string, number>());
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

  function disposePluginRenderResult(pluginView?: PluginRenderResult | null) {
    if (!pluginView || pluginView.mode !== "session") {
      return;
    }
    void client.disposePluginViewSession(botAlias, pluginView.pluginId, pluginView.sessionId).catch(() => {});
  }

  function disposePluginSession(tab?: EditorTab | null) {
    disposePluginRenderResult(tab?.pluginView);
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

  async function openExternalSource(input: {
    sourceId: string;
    displayPath?: string;
  } | string): Promise<boolean> {
    if (structureOnly) {
      return false;
    }
    const generation = scopeGenerationRef.current;
    const sourceId = typeof input === "string" ? input.trim() : String(input.sourceId || "").trim();
    if (!sourceId) {
      return false;
    }
    const requestedDisplayPath = typeof input === "string" ? "" : String(input.displayPath || "").trim();
    const path = externalTabPath(sourceId);
    const existing = tabsRef.current.find((item) => item.kind === "external-source" && item.sourceId === sourceId);
    const initialTab = existing || createTab(path, "", undefined, {
      basename: externalDisplayName(requestedDisplayPath, sourceId),
      kind: "external-source",
      sourceId,
      displayPath: requestedDisplayPath,
      readOnly: true,
      statusText: "外部依赖 · 只读",
      loading: true,
      contentPersistence: "none",
    });
    const currentTabs = tabsRef.current;
    if (!existing) {
      tabsRef.current = [...currentTabs, initialTab];
      setTabs(tabsRef.current);
    } else {
      tabsRef.current = currentTabs.map((item) => item.path === existing.path
        ? { ...item, loading: true, error: "", statusText: "外部依赖 · 只读" }
        : item);
      setTabs(tabsRef.current);
    }
    activeTabPathRef.current = path;
    setActiveTabPath(path);

    try {
      const result: ExternalSourceReadResult = await client.readExternalSource(botAlias, sourceId);
      if (!isCurrentScope(generation)) {
        return false;
      }
      const displayPath = result.displayPath || requestedDisplayPath || "外部源码";
      const nextTab: EditorTab = {
        ...(initialTab || createTab(path, "")),
        path,
        basename: externalDisplayName(displayPath, sourceId),
        content: result.content || "",
        documentVersion: Math.max(1, Math.trunc(Number(initialTab.documentVersion) || 1)),
        savedContent: result.content || "",
        kind: "external-source",
        sourceId: result.sourceId || sourceId,
        displayPath,
        readOnly: true,
        dirty: false,
        loading: false,
        saving: false,
        statusText: "外部依赖 · 只读",
        error: "",
        lastModifiedNs: result.lastModifiedNs,
        encoding: result.encoding,
        cold: false,
        missing: false,
        contentPersistence: "none",
      };
      const nextTabs = tabsRef.current.some((item) => item.path === path)
        ? tabsRef.current.map((item) => item.path === path ? nextTab : item)
        : [...tabsRef.current, nextTab];
      tabsRef.current = nextTabs;
      setTabs(nextTabs);
      activeTabPathRef.current = path;
      setActiveTabPath(path);
      return true;
    } catch (error) {
      if (!isCurrentScope(generation)) {
        return false;
      }
      const message = getExternalSourceErrorMessage(error);
      const nextTabs = tabsRef.current.map((item) => item.path === path
        ? {
            ...item,
            basename: externalDisplayName(requestedDisplayPath || item.basename, sourceId),
            kind: "external-source" as const,
            sourceId,
            displayPath: requestedDisplayPath || item.displayPath,
            readOnly: true,
            loading: false,
            saving: false,
            statusText: "外部依赖 · 只读",
            error: message,
            contentPersistence: "none" as const,
          }
        : item);
      tabsRef.current = nextTabs;
      setTabs(nextTabs);
      return false;
    }
  }

  async function openPluginView(target: PluginOpenTarget, options?: { activate?: boolean }) {
    if (structureOnly) {
      return;
    }
    const generation = scopeGenerationRef.current;
    const nextTarget = clonePluginTarget(target);
    const sourcePath = typeof target.input.path === "string" ? target.input.path : undefined;
    const tabPath = pluginViewTabPath(target);
    const requestSeq = pluginViewRequestSerialRef.current + 1;
    pluginViewRequestSerialRef.current = requestSeq;
    pluginViewRequestSeqRef.current.set(tabPath, requestSeq);
    const currentTabs = tabsRef.current;
    const existingIndex = currentTabs.findIndex((item) => item.path === tabPath);
    const existing = existingIndex >= 0 ? currentTabs[existingIndex] : undefined;
    const loadingTab = existing
      ? {
          ...existing,
          basename: target.title,
          kind: "plugin-view" as const,
          pluginOpenTarget: nextTarget,
          pluginInput: { ...target.input },
          sourcePath,
          readOnly: true,
          statusText: "插件视图",
          loading: true,
          error: "",
        }
      : createTab(tabPath, "", undefined, {
          basename: target.title,
          kind: "plugin-view",
          pluginOpenTarget: nextTarget,
          pluginInput: { ...target.input },
          sourcePath,
          readOnly: true,
          statusText: "插件视图",
          loading: true,
          contentPersistence: "none",
        });
    const loadingTabs = existingIndex >= 0 ? currentTabs.slice() : [...currentTabs, loadingTab];
    if (existingIndex >= 0) {
      loadingTabs[existingIndex] = loadingTab;
    }
    tabsRef.current = loadingTabs;
    setTabs(loadingTabs);
    if (options?.activate !== false) {
      activeTabPathRef.current = tabPath;
      setActiveTabPath(tabPath);
    }

    try {
      const view = await client.openPluginView(botAlias, target.pluginId, target.viewId, target.input);
      if (
        !isCurrentScope(generation)
        || pluginViewRequestSeqRef.current.get(tabPath) !== requestSeq
        || !tabsRef.current.some((item) => item.path === tabPath)
      ) {
        disposePluginRenderResult(view);
        return;
      }
      const currentTab = tabsRef.current.find((item) => item.path === tabPath);
      const nextTab = createTab(tabPath, "", undefined, {
        basename: target.title,
        kind: "plugin-view",
        pluginOpenTarget: nextTarget,
        pluginView: view,
        pluginInput: { ...target.input },
        sourcePath,
        readOnly: true,
        statusText: "插件视图",
        loading: false,
        contentPersistence: "none",
      });
      if (
        currentTab?.pluginView?.mode === "session"
        && (view.mode !== "session" || currentTab.pluginView.sessionId !== view.sessionId)
      ) {
        disposePluginRenderResult(currentTab.pluginView);
      }
      setTabs((current) => {
        const existingIndex = current.findIndex((item) => item.path === tabPath);
        if (existingIndex < 0) {
          tabsRef.current = current;
          return current;
        }
        const next = current.slice();
        next[existingIndex] = nextTab;
        tabsRef.current = next;
        return next;
      });
    } catch (error) {
      if (
        !isCurrentScope(generation)
        || pluginViewRequestSeqRef.current.get(tabPath) !== requestSeq
      ) {
        return;
      }
      const message = error instanceof Error ? error.message : "打开插件视图失败";
      setTabs((current) => {
        const next = current.map((item) => item.path === tabPath
            ? {
                ...item,
                basename: target.title,
                kind: "plugin-view" as const,
                pluginOpenTarget: nextTarget,
                pluginInput: { ...target.input },
                sourcePath,
                readOnly: true,
                loading: false,
                error: message,
                statusText: "插件视图",
              }
          : item);
        tabsRef.current = next;
        return next;
      });
    } finally {
      if (pluginViewRequestSeqRef.current.get(tabPath) === requestSeq) {
        pluginViewRequestSeqRef.current.delete(tabPath);
      }
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

  function openFilePreview(input: {
    path: string;
    result?: FileReadResult | null;
    loading?: boolean;
    statusText?: string;
    error?: string;
    activate?: boolean;
  }) {
    if (structureOnly) {
      return "";
    }
    const sourcePath = input.path.trim();
    if (!sourcePath) {
      return "";
    }

    const tabPath = filePreviewTabPath(sourcePath);
    const buildPreviewTab = (existing?: EditorTab) => {
      const filePreview = input.result === undefined
        ? existing?.filePreview
        : input.result || undefined;
      return createTab(
        tabPath,
        filePreview?.previewKind === "image" ? "" : filePreview?.content || "",
        filePreview?.lastModifiedNs,
        {
          basename: basename(sourcePath),
          kind: "file-preview",
          filePreview,
          sourcePath,
          readOnly: true,
          loading: Boolean(input.loading),
          statusText: input.statusText ?? existing?.statusText ?? "",
          error: input.error ?? "",
          contentPersistence: "none",
        },
      );
    };
    if (input.activate !== false) {
      const currentTabs = tabsRef.current;
      const existingIndex = currentTabs.findIndex((item) => item.path === tabPath);
      const nextTab = buildPreviewTab(existingIndex >= 0 ? currentTabs[existingIndex] : undefined);
      const nextTabs = existingIndex >= 0 ? currentTabs.slice() : [...currentTabs, nextTab];
      if (existingIndex >= 0) {
        nextTabs[existingIndex] = nextTab;
      }
      tabsRef.current = nextTabs;
    }
    setTabs((current) => {
      const existingIndex = current.findIndex((item) => item.path === tabPath);
      const existing = existingIndex >= 0 ? current[existingIndex] : undefined;
      if (!existing && input.activate === false) {
        tabsRef.current = current;
        return current;
      }
      const nextTab = buildPreviewTab(existing);
      const nextTabs = existingIndex >= 0 ? current.slice() : [...current, nextTab];
      if (existingIndex >= 0) {
        nextTabs[existingIndex] = nextTab;
      }
      tabsRef.current = nextTabs;
      return nextTabs;
    });
    if (input.activate !== false) {
      activeTabPathRef.current = tabPath;
      setActiveTabPath(tabPath);
    }
    return tabPath;
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
        tabsRef.current = current;
        return current;
      }
      const nextTabs = current.filter((item) => item.path !== path);
      tabsRef.current = nextTabs;
      if (activeTabPathRef.current !== path) {
        return nextTabs;
      }
      const nextActive = nextTabs[Math.max(0, index - 1)]?.path || nextTabs[nextTabs.length - 1]?.path || "";
      activeTabPathRef.current = nextActive;
      setActiveTabPath(nextActive);
      return nextTabs;
    });
  }

  function closeDeletedPath(path: string) {
    const removedTabs = tabsRef.current.filter((item) => {
      const sourcePath = editorTabSourcePath(item);
      return sourcePath && isSameOrDescendantSourcePath(sourcePath, path);
    });
    if (removedTabs.length > 0) {
      void closeDocuments(removedTabs);
      removedTabs.forEach((item) => disposePluginSession(item));
    }

    setTabs((current) => {
      const activeIndex = current.findIndex((item) => item.path === activeTabPathRef.current);
      const nextTabs = current.filter((item) => {
        const sourcePath = editorTabSourcePath(item);
        return !sourcePath || !isSameOrDescendantSourcePath(sourcePath, path);
      });
      tabsRef.current = nextTabs;
      if (nextTabs.some((item) => item.path === activeTabPathRef.current)) {
        return nextTabs;
      }
      const nextActive = nextTabs[Math.max(0, activeIndex - 1)]?.path || nextTabs[nextTabs.length - 1]?.path || "";
      activeTabPathRef.current = nextActive;
      setActiveTabPath(nextActive);
      return nextTabs;
    });
    setClosedTabs((current) => {
      const nextClosedTabs = current.filter((item) => !isSameOrDescendantSourcePath(item.path, path));
      closedTabsRef.current = nextClosedTabs;
      return nextClosedTabs;
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

  function closeAllTabs() {
    const closingTabs = tabsRef.current;
    if (closingTabs.some((item) => item.dirty) && !window.confirm("存在未保存的文件，确定关闭全部并放弃修改吗？")) {
      return false;
    }
    closingTabs.forEach((item) => {
      pushClosedTab(item.path);
      disposePluginSession(item);
    });
    void closeDocuments(closingTabs);
    tabsRef.current = [];
    setTabs([]);
    activeTabPathRef.current = "";
    setActiveTabPath("");
    return true;
  }

  function closeOtherTabs(path: string) {
    const currentTabs = tabsRef.current;
    const nextClosed = currentTabs.filter((item) => item.path !== path);
    nextClosed.forEach((item) => pushClosedTab(item.path));
    nextClosed.forEach((item) => disposePluginSession(item));
    void closeDocuments(nextClosed);
    const nextTabs = currentTabs.filter((item) => item.path === path);
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    const nextActivePath = nextTabs[0]?.path || "";
    activeTabPathRef.current = nextActivePath;
    setActiveTabPath(nextActivePath);
  }

  function closeTabsToRight(path: string) {
    const currentTabs = tabsRef.current;
    const index = currentTabs.findIndex((item) => item.path === path);
    if (index < 0) {
      return;
    }
    const closingTabs = currentTabs.slice(index + 1);
    closingTabs.forEach((item) => {
      pushClosedTab(item.path);
      disposePluginSession(item);
    });
    void closeDocuments(closingTabs);
    const nextTabs = currentTabs.slice(0, index + 1);
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    if (!nextTabs.some((item) => item.path === activeTabPathRef.current)) {
      activeTabPathRef.current = path;
      setActiveTabPath(path);
    }
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
    const generation = scopeGenerationRef.current;
    const currentTabs = tabsRef.current;
    const nextTabs = currentTabs.map((item) => {
      const sourcePath = editorTabSourcePath(item);
      const nextSourcePath = sourcePath ? remapEditorSourcePath(sourcePath, oldPath, nextPath) : sourcePath;
      if (!sourcePath || nextSourcePath === sourcePath) {
        return item;
      }
      if (item.kind === "file") {
        return {
          ...item,
          path: nextSourcePath,
          basename: basename(nextSourcePath),
          pluginTargets: item.pluginTargets?.map((target) => remapPluginTarget(target, oldPath, nextPath)),
        };
      }
      if (item.kind === "file-preview") {
        return {
          ...item,
          path: filePreviewTabPath(nextSourcePath),
          sourcePath: nextSourcePath,
          basename: basename(nextSourcePath),
        };
      }
      if (item.kind === "plugin-view") {
        const nextPluginTarget = item.pluginOpenTarget
          ? remapPluginTarget(item.pluginOpenTarget, oldPath, nextPath)
          : undefined;
        const nextTabPath = nextPluginTarget
          ? pluginViewTabPath(nextPluginTarget)
          : item.sourcePath && item.path.endsWith(item.sourcePath)
            ? `${item.path.slice(0, -item.sourcePath.length)}${nextSourcePath}`
            : item.path;
        return {
          ...item,
          path: nextTabPath,
          sourcePath: nextSourcePath,
          pluginOpenTarget: nextPluginTarget,
          pluginInput: item.pluginInput
            ? { ...item.pluginInput, path: nextSourcePath }
            : item.pluginInput,
        };
      }
      return {
        ...item,
        sourcePath: nextSourcePath,
      };
    });
    const renamedDocuments = currentTabs.flatMap((item, index) => {
      const nextTab = nextTabs[index];
      return isSyncableTab(item) && isSyncableTab(nextTab) && item.path !== nextTab.path
        ? [{ previous: item, next: nextTab }]
        : [];
    });
    const activeIndex = currentTabs.findIndex((item) => item.path === activeTabPathRef.current);
    const nextActivePath = activeIndex >= 0 ? nextTabs[activeIndex]?.path || "" : activeTabPathRef.current;
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    if (nextActivePath !== activeTabPathRef.current) {
      activeTabPathRef.current = nextActivePath;
      setActiveTabPath(nextActivePath);
    }
    setClosedTabs((current) => {
      const nextClosedTabs = current.map((item) => {
        const remappedPath = remapEditorSourcePath(item.path, oldPath, nextPath);
        return remappedPath === item.path ? item : { ...item, path: remappedPath };
      });
      closedTabsRef.current = nextClosedTabs;
      return nextClosedTabs;
    });
    if (renamedDocuments.length > 0) {
      void (async () => {
        await closeDocuments(renamedDocuments.map((item) => item.previous));
        if (!isCurrentScope(generation)) {
          return;
        }
        renamedDocuments.forEach((item) => queueDocumentSync(item.next, "didOpen"));
        await flushDocumentSync();
      })();
    }
    return {
      previews: currentTabs.flatMap((item, index) => item.kind === "file-preview" && nextTabs[index]?.sourcePath !== item.sourcePath
        ? [{
            path: nextTabs[index]?.sourcePath || "",
            loading: item.loading,
            full: item.statusText === "正在读取全文",
          }]
        : []),
      pluginTargets: currentTabs.flatMap((item, index) => (
        item.kind === "plugin-view"
        && nextTabs[index]?.path !== item.path
        && nextTabs[index]?.pluginOpenTarget
      ) ? [nextTabs[index].pluginOpenTarget] : []),
    };
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
      })).filter((tab) => (
        tab.kind !== "file-preview"
        && tab.kind !== "git-diff"
        && tab.kind !== "plugin-view"
        && tab.kind !== "external-source"
      )),
    );
  }

  return {
    tabs,
    activeTab,
    activeTabPath,
    hasDirtyTabs,
    closedTabs,
    openFile,
    openExternalSource,
    openPluginView,
    openFilePreview,
    openReadOnlyTab,
    openCreatedFile,
    restoreFromSnapshot,
    buildPersistenceSnapshot,
    activateTab,
    updateActiveContent,
    saveActiveTab,
    closeTab,
    closeAllTabs,
    closePath,
    closeDeletedPath,
    closeOtherTabs,
    closeTabsToRight,
    reopenLastClosedTab,
    syncRenamedPath,
  };
}
