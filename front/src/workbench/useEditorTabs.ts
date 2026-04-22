import { useEffect, useRef, useState } from "react";
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
};

function basename(path: string) {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
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
    savedContent: content,
    dirty: false,
    loading: false,
    saving: false,
    statusText: "",
    error: "",
    lastModifiedNs,
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
      contentPersistence: "dirty_snapshot",
    });
  }

  if (tab.contentPersistence === "clean_snapshot") {
    const savedContent = tab.savedContent ?? "";
    return createTab(tab.path, savedContent, tab.lastModifiedNs, {
      contentPersistence: "clean_snapshot",
    });
  }

  return createTab(tab.path, "", tab.lastModifiedNs, {
    cold: true,
    contentPersistence: "none",
  });
}

export function useEditorTabs({ botAlias, client }: Props) {
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTabPath, setActiveTabPath] = useState("");
  const [closedTabs, setClosedTabs] = useState<PersistedWorkbenchTab[]>([]);
  const tabsRef = useRef<EditorTab[]>([]);
  const activeTabPathRef = useRef("");
  const closedTabsRef = useRef<PersistedWorkbenchTab[]>([]);

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
    tabsRef.current.forEach((tab) => disposePluginSession(tab));
  }, [botAlias, client]);

  useEffect(() => {
    setTabs([]);
    setActiveTabPath("");
    setClosedTabs([]);
  }, [botAlias, client]);

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
      lastModifiedNs: target.lastModifiedNs,
      savedContent: target.savedContent,
      draftContent: target.content,
      contentPersistence: target.dirty ? "dirty_snapshot" : "clean_snapshot",
    };

    setClosedTabs((current) => [
      nextClosedTab,
      ...current.filter((item) => item.path !== path),
    ].slice(0, CLOSED_TAB_HISTORY_LIMIT));
  }

  async function hydrateTabContent(path: string) {
    const target = tabsRef.current.find((item) => item.path === path);
    if (target && !target.cold && !target.missing) {
      return;
    }

    setTabs((current) => current.some((item) => item.path === path)
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
      setTabs((current) => current.some((item) => item.path === path)
        ? current.map((item) => item.path === path
          ? {
              ...item,
              basename: basename(path),
              content: result.content || "",
              savedContent: result.content || "",
              dirty: false,
              loading: false,
              saving: false,
              error: "",
              statusText: "",
              lastModifiedNs: result.lastModifiedNs,
              cold: false,
              missing: false,
              contentPersistence: "none",
            }
          : item)
        : current);
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取文件失败";
      setTabs((current) => current.some((item) => item.path === path)
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
    setTabs((current) => {
      const nextTab = createTab(path, content, lastModifiedNs, {
        contentPersistence: "none",
      });
      const existingIndex = current.findIndex((item) => item.path === path);
      if (existingIndex >= 0) {
        const nextTabs = current.slice();
        nextTabs[existingIndex] = nextTab;
        return nextTabs;
      }
      return [...current, nextTab];
    });
    setActiveTabPath(path);
  }

  async function openFile(path: string) {
    const existing = tabsRef.current.find((item) => item.path === path);
    if (existing) {
      setActiveTabPath(path);
      if (existing.cold || existing.missing) {
        await hydrateTabContent(path);
      }
      return;
    }

    setTabs((current) => [
      ...current,
      createTab(path, "", undefined, {
        loading: true,
        cold: true,
      }),
    ]);
    setActiveTabPath(path);
    await hydrateTabContent(path);
  }

  async function openPluginView(target: {
    pluginId: string;
    viewId: string;
    title: string;
    input: Record<string, unknown>;
  }) {
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
        sourcePath,
        readOnly: true,
        statusText: "插件视图",
        loading: false,
        contentPersistence: "none",
      });
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
    const target = tabsRef.current.find((item) => item.path === path);
    if (target?.cold || target?.missing) {
      await hydrateTabContent(path);
    }
  }

  function updateActiveContent(content: string) {
    setTabs((current) => current.map((item) => {
      if (item.path !== activeTabPathRef.current) {
        return item;
      }
      if (item.readOnly) {
        return item;
      }
      return {
        ...item,
        content,
        dirty: content !== item.savedContent,
        statusText: "",
        error: "",
        missing: false,
      };
    }));
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

    setTabs((current) => current.map((item) => item.path === target.path
      ? { ...item, saving: true, error: "", statusText: "" }
      : item));

    try {
      const result = await client.writeFile(botAlias, target.path, target.content, target.lastModifiedNs);
      setTabs((current) => current.map((item) => item.path === target.path
        ? {
            ...item,
            saving: false,
            dirty: false,
            savedContent: item.content,
            statusText: "已保存",
            error: "",
            lastModifiedNs: result.lastModifiedNs,
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
    disposePluginSession(tabsRef.current.find((item) => item.path === path));
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
    setTabs((current) => current.slice(0, index + 1));
  }

  async function reopenLastClosedTab() {
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
        lastModifiedNs: tab.lastModifiedNs,
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
