import { useEffect, useState } from "react";
import type { WebBotClient } from "../services/webBotClient";
import type { EditorTab } from "./workbenchTypes";

type Props = {
  botAlias: string;
  client: WebBotClient;
};

function createTab(path: string, content: string, lastModifiedNs?: string): EditorTab {
  return {
    path,
    content,
    savedContent: content,
    dirty: false,
    loading: false,
    saving: false,
    statusText: "",
    error: "",
    lastModifiedNs,
  };
}

export function useEditorTabs({ botAlias, client }: Props) {
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTabPath, setActiveTabPath] = useState("");

  useEffect(() => {
    setTabs([]);
    setActiveTabPath("");
  }, [botAlias, client]);

  const activeTab = tabs.find((tab) => tab.path === activeTabPath) || null;
  const hasDirtyTabs = tabs.some((tab) => tab.dirty);

  function openCreatedFile(path: string, content: string, lastModifiedNs?: string) {
    setTabs((current) => {
      const nextTab = createTab(path, content, lastModifiedNs);
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
    const existing = tabs.find((item) => item.path === path);
    if (existing) {
      setActiveTabPath(path);
      return;
    }

    const result = await client.readFileFull(botAlias, path);
    openCreatedFile(path, result.content || "", result.lastModifiedNs);
  }

  function activateTab(path: string) {
    setActiveTabPath(path);
  }

  function updateActiveContent(content: string) {
    setTabs((current) => current.map((item) => {
      if (item.path !== activeTabPath) {
        return item;
      }
      return {
        ...item,
        content,
        dirty: content !== item.savedContent,
        statusText: "",
      };
    }));
  }

  async function saveActiveTab() {
    if (!activeTab) {
      return;
    }

    setTabs((current) => current.map((item) => item.path === activeTab.path
      ? { ...item, saving: true, error: "", statusText: "" }
      : item));

    try {
      const result = await client.writeFile(botAlias, activeTab.path, activeTab.content, activeTab.lastModifiedNs);
      setTabs((current) => current.map((item) => item.path === activeTab.path
        ? {
            ...item,
            saving: false,
            dirty: false,
            savedContent: item.content,
            statusText: "已保存",
            error: "",
            lastModifiedNs: result.lastModifiedNs,
          }
        : item));
    } catch (error) {
      const message = error instanceof Error ? error.message : "保存失败";
      setTabs((current) => current.map((item) => item.path === activeTab.path
        ? { ...item, saving: false, error: message }
        : item));
    }
  }

  function closePath(path: string) {
    setTabs((current) => {
      const nextTabs = current.filter((item) => item.path !== path);
      if (activeTabPath !== path) {
        return nextTabs;
      }
      const nextActive = nextTabs[nextTabs.length - 1]?.path || "";
      setActiveTabPath(nextActive);
      return nextTabs;
    });
  }

  function closeTab(path: string) {
    const target = tabs.find((item) => item.path === path);
    if (!target) {
      return true;
    }
    if (target.dirty && !window.confirm("文件尚未保存，确定放弃修改吗？")) {
      return false;
    }
    closePath(path);
    return true;
  }

  function syncRenamedPath(oldPath: string, nextPath: string) {
    setTabs((current) => current.map((item) => item.path === oldPath ? { ...item, path: nextPath } : item));
    setActiveTabPath((current) => current === oldPath ? nextPath : current);
  }

  return {
    tabs,
    activeTab,
    activeTabPath,
    hasDirtyTabs,
    openFile,
    openCreatedFile,
    activateTab,
    updateActiveContent,
    saveActiveTab,
    closeTab,
    closePath,
    syncRenamedPath,
  };
}
