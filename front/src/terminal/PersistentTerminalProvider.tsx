import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { PersistentTerminalSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import type { TerminalRecoverySnapshot } from "./terminalRecovery";
import {
  createStoredTerminalTab,
  readTerminalTabs,
  writeTerminalTabs,
  type StoredTerminalTab,
} from "./terminalStorage";

export type PersistentTerminalPhase = "not_started" | "running" | "closed" | "error";
export type PersistentTerminalTab = StoredTerminalTab;

type CreateTerminalTabOptions = {
  title?: string;
  cwd?: string;
  shell?: string;
  start?: boolean;
  activate?: boolean;
  terminalActionBotAlias?: string;
  terminalActionId?: string;
};

type PersistentTerminalContextValue = {
  tabs: PersistentTerminalTab[];
  activeTabId: string;
  activeTab?: PersistentTerminalTab;
  ownerId: string;
  snapshot: PersistentTerminalSnapshot;
  phase: PersistentTerminalPhase;
  error: string;
  attachNonce: number;
  getClientRecoveryState: (ownerId: string) => TerminalRecoverySnapshot | null;
  setClientRecoveryState: (ownerId: string, state: TerminalRecoverySnapshot) => void;
  refreshSnapshot: (ownerId?: string) => Promise<void>;
  createTab: (options?: CreateTerminalTabOptions) => Promise<PersistentTerminalTab>;
  selectTab: (tabId: string) => void;
  updateTab: (tabId: string, patch: Partial<Pick<PersistentTerminalTab, "title" | "cwd" | "shell">>) => void;
  closeTab: (tabId: string) => Promise<void>;
  create: (cwd: string, shell?: string) => Promise<void>;
  rebuild: (cwd: string, shell?: string) => Promise<void>;
  close: () => Promise<void>;
};

const DEFAULT_SNAPSHOT: PersistentTerminalSnapshot = {
  started: false,
  closed: false,
  cwd: "",
  ptyMode: null,
  connectionText: "未启动",
  lastSeq: 0,
};

const PersistentTerminalContext = createContext<PersistentTerminalContextValue | null>(null);

function resolvePhase(snapshot: PersistentTerminalSnapshot, error: string): PersistentTerminalPhase {
  if (error) {
    return "error";
  }
  if (snapshot.started) {
    return "running";
  }
  if (snapshot.closed) {
    return "closed";
  }
  return "not_started";
}

function replaceTab(tabs: PersistentTerminalTab[], tabId: string, patch: Partial<PersistentTerminalTab>) {
  return tabs.map((tab) => tab.id === tabId || tab.ownerId === tabId ? { ...tab, ...patch } : tab);
}

type Props = {
  client: WebBotClient;
  children: ReactNode;
};

export function PersistentTerminalProvider({ client, children }: Props) {
  const [initialTabs] = useState<PersistentTerminalTab[]>(() => readTerminalTabs());
  const [tabs, setTabs] = useState<PersistentTerminalTab[]>(initialTabs);
  const [activeTabId, setActiveTabId] = useState(() => initialTabs[0]?.id || "");
  const [snapshots, setSnapshots] = useState<Record<string, PersistentTerminalSnapshot>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [attachNonce, setAttachNonce] = useState(0);
  const tabsRef = useRef(tabs);
  const activeTabIdRef = useRef(activeTabId);
  const clientRecoveryStatesRef = useRef<Record<string, TerminalRecoverySnapshot>>({});

  const activeTab = tabs.find((tab) => tab.id === activeTabId);
  const activeOwnerId = activeTab?.ownerId || "";
  const snapshot = activeOwnerId ? snapshots[activeOwnerId] || DEFAULT_SNAPSHOT : DEFAULT_SNAPSHOT;
  const error = activeOwnerId ? errors[activeOwnerId] || "" : "";
  const phase = resolvePhase(snapshot, error);

  useEffect(() => {
    tabsRef.current = tabs;
    writeTerminalTabs(tabs);
  }, [tabs]);

  useEffect(() => {
    activeTabIdRef.current = activeTabId;
  }, [activeTabId]);

  const setSnapshotFor = useCallback((ownerId: string, next: PersistentTerminalSnapshot) => {
    if (!ownerId) {
      return;
    }
    setSnapshots((current) => ({ ...current, [ownerId]: next }));
    setErrors((current) => {
      if (!current[ownerId]) {
        return current;
      }
      const nextErrors = { ...current };
      delete nextErrors[ownerId];
      return nextErrors;
    });
    if (next.cwd) {
      setTabs((current) => replaceTab(current, ownerId, { cwd: next.cwd }));
    }
  }, []);

  const getClientRecoveryState = useCallback((ownerId: string) => {
    return ownerId ? clientRecoveryStatesRef.current[ownerId] || null : null;
  }, []);

  const setClientRecoveryState = useCallback((ownerId: string, state: TerminalRecoverySnapshot) => {
    if (!ownerId) {
      return;
    }
    clientRecoveryStatesRef.current[ownerId] = { ...state };
  }, []);

  const refreshSnapshot = useCallback(async (requestedOwnerId?: string) => {
    const targetOwnerId = requestedOwnerId || tabsRef.current.find((tab) => tab.id === activeTabIdRef.current)?.ownerId || "";
    if (!targetOwnerId) {
      return;
    }
    try {
      const next = await client.getTerminalSession(targetOwnerId);
      setSnapshotFor(targetOwnerId, next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "无法读取终端状态";
      setErrors((current) => ({ ...current, [targetOwnerId]: message }));
    }
  }, [client, setSnapshotFor]);

  useEffect(() => {
    void refreshSnapshot(activeOwnerId);
  }, [activeOwnerId, refreshSnapshot]);

  const createTab = useCallback(async (options: CreateTerminalTabOptions = {}) => {
    const tab = createStoredTerminalTab(tabsRef.current, options);
    const nextTabs = [...tabsRef.current, tab];
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    if (options.activate !== false) {
      activeTabIdRef.current = tab.id;
      setActiveTabId(tab.id);
    }
    if (options.start === false) {
      return tab;
    }
    try {
      const next = await client.createTerminalSession(tab.ownerId, tab.cwd, tab.shell);
      setSnapshotFor(tab.ownerId, next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "新建终端失败";
      setErrors((current) => ({ ...current, [tab.ownerId]: message }));
    }
    return tab;
  }, [client, setSnapshotFor]);

  const selectTab = useCallback((tabId: string) => {
    if (!tabsRef.current.some((tab) => tab.id === tabId)) {
      return;
    }
    activeTabIdRef.current = tabId;
    setActiveTabId(tabId);
  }, []);

  const updateTab = useCallback((tabId: string, patch: Partial<Pick<PersistentTerminalTab, "title" | "cwd" | "shell">>) => {
    setTabs((current) => replaceTab(current, tabId, patch));
  }, []);

  const closeTab = useCallback(async (tabId: string) => {
    const currentTabs = tabsRef.current;
    const tabIndex = currentTabs.findIndex((tab) => tab.id === tabId);
    if (tabIndex < 0) {
      return;
    }
    const tab = currentTabs[tabIndex];
    try {
      await client.closeTerminalSession(tab.ownerId);
    } catch (err) {
      const message = err instanceof Error ? err.message : "关闭终端失败";
      setErrors((current) => ({ ...current, [tab.ownerId]: message }));
      throw err;
    }
    const nextTabs = currentTabs.filter((item) => item.id !== tabId);
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    setSnapshots((current) => {
      const next = { ...current };
      delete next[tab.ownerId];
      return next;
    });
    setErrors((current) => {
      const next = { ...current };
      delete next[tab.ownerId];
      return next;
    });
    delete clientRecoveryStatesRef.current[tab.ownerId];
    if (activeTabIdRef.current === tabId) {
      const nextActive = nextTabs[Math.min(tabIndex, Math.max(nextTabs.length - 1, 0))];
      activeTabIdRef.current = nextActive?.id || "";
      setActiveTabId(nextActive?.id || "");
    }
    setAttachNonce((current) => current + 1);
  }, [client]);

  const create = useCallback(async (cwd: string, shell = "auto") => {
    await createTab({ cwd, shell });
  }, [createTab]);

  const rebuild = useCallback(async (cwd: string, shell = "auto") => {
    await create(cwd, shell);
  }, [create]);

  const close = useCallback(async () => {
    const ownerId = tabsRef.current.find((tab) => tab.id === activeTabIdRef.current)?.ownerId || "";
    if (ownerId) {
      await closeTab(activeTabIdRef.current);
    }
  }, [closeTab]);

  const value = useMemo<PersistentTerminalContextValue>(() => ({
    tabs,
    activeTabId,
    activeTab,
    ownerId: activeOwnerId,
    snapshot,
    phase,
    error,
    attachNonce,
    getClientRecoveryState,
    setClientRecoveryState,
    refreshSnapshot,
    createTab,
    selectTab,
    updateTab,
    closeTab,
    create,
    rebuild,
    close,
  }), [
    activeOwnerId,
    activeTab,
    activeTabId,
    attachNonce,
    close,
    closeTab,
    create,
    createTab,
    error,
    getClientRecoveryState,
    phase,
    rebuild,
    refreshSnapshot,
    selectTab,
    setClientRecoveryState,
    snapshot,
    tabs,
    updateTab,
  ]);

  return (
    <PersistentTerminalContext.Provider value={value}>
      {children}
    </PersistentTerminalContext.Provider>
  );
}

export function usePersistentTerminal() {
  const context = useContext(PersistentTerminalContext);
  if (!context) {
    throw new Error("PersistentTerminalProvider 缺失");
  }
  return context;
}
