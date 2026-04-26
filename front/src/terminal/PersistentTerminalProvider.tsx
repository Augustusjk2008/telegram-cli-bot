import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { PersistentTerminalSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { readTerminalOwnerId } from "./terminalStorage";

export type PersistentTerminalPhase = "not_started" | "running" | "closed" | "error";

type PersistentTerminalContextValue = {
  ownerId: string;
  snapshot: PersistentTerminalSnapshot;
  phase: PersistentTerminalPhase;
  error: string;
  attachNonce: number;
  refreshSnapshot: () => Promise<void>;
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

function resolvePhase(snapshot: PersistentTerminalSnapshot): PersistentTerminalPhase {
  if (snapshot.started) {
    return "running";
  }
  if (snapshot.closed) {
    return "closed";
  }
  return "not_started";
}

type Props = {
  client: WebBotClient;
  children: ReactNode;
};

export function PersistentTerminalProvider({ client, children }: Props) {
  const ownerIdRef = useRef(readTerminalOwnerId());
  const [snapshot, setSnapshot] = useState<PersistentTerminalSnapshot>(DEFAULT_SNAPSHOT);
  const [phase, setPhase] = useState<PersistentTerminalPhase>("not_started");
  const [error, setError] = useState("");
  const [attachNonce, setAttachNonce] = useState(0);

  const refreshSnapshot = useCallback(async () => {
    try {
      const next = await client.getTerminalSession(ownerIdRef.current);
      setSnapshot(next);
      setPhase(resolvePhase(next));
      setError("");
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "无法读取终端状态");
    }
  }, [client]);

  const rebuild = useCallback(async (cwd: string, shell = "auto") => {
    const next = await client.rebuildTerminalSession(ownerIdRef.current, cwd, shell);
    setSnapshot(next);
    setPhase(resolvePhase(next));
    setError("");
    setAttachNonce((current) => current + 1);
  }, [client]);

  const close = useCallback(async () => {
    const next = await client.closeTerminalSession(ownerIdRef.current);
    setSnapshot(next);
    setPhase(resolvePhase(next));
    setError("");
    setAttachNonce((current) => current + 1);
  }, [client]);

  useEffect(() => {
    void refreshSnapshot();
  }, [refreshSnapshot]);

  const value = useMemo<PersistentTerminalContextValue>(() => ({
    ownerId: ownerIdRef.current,
    snapshot,
    phase,
    error,
    attachNonce,
    refreshSnapshot,
    rebuild,
    close,
  }), [attachNonce, close, error, phase, rebuild, refreshSnapshot, snapshot]);

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
