import { useEffect, useMemo, useRef, useState } from "react";
import {
  WORKBENCH_SESSION_VERSION,
  WORKBENCH_SESSION_WRITE_DELAY_MS,
  type PersistedWorkbenchSession,
  type WorkbenchRestoreState,
} from "./workbenchTypes";
import { readWorkbenchSession, writeWorkbenchSession } from "./workbenchSession";

type Props = {
  botAlias: string;
  workspaceRoot: string;
  snapshot: Omit<PersistedWorkbenchSession, "version" | "botAlias" | "workspaceRoot"> | null;
};

export function useWorkbenchSession({ botAlias, workspaceRoot, snapshot }: Props) {
  const [restoredSession, setRestoredSession] = useState<PersistedWorkbenchSession | null>(null);
  const [restoreState, setRestoreState] = useState<WorkbenchRestoreState>("clean");
  const [restoreApplied, setRestoreApplied] = useState(false);
  const writeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    setRestoreApplied(false);
    if (!workspaceRoot) {
      setRestoredSession(null);
      setRestoreState("clean");
      return;
    }

    const nextSession = readWorkbenchSession(botAlias, workspaceRoot);
    setRestoredSession(nextSession);
    setRestoreState(
      nextSession?.tabs.some((tab) => tab.contentPersistence === "dirty_snapshot")
        ? "draft-only"
        : nextSession
          ? "restored"
          : "clean",
    );
  }, [botAlias, workspaceRoot]);

  const persistedSnapshot = useMemo(() => {
    if (!workspaceRoot || !snapshot) {
      return null;
    }

    return {
      version: WORKBENCH_SESSION_VERSION,
      botAlias,
      workspaceRoot,
      ...snapshot,
    } satisfies PersistedWorkbenchSession;
  }, [botAlias, snapshot, workspaceRoot]);

  useEffect(() => {
    if (!persistedSnapshot || !restoreApplied) {
      return;
    }

    if (writeTimerRef.current !== null) {
      window.clearTimeout(writeTimerRef.current);
    }

    writeTimerRef.current = window.setTimeout(() => {
      writeWorkbenchSession(persistedSnapshot);
      writeTimerRef.current = null;
    }, WORKBENCH_SESSION_WRITE_DELAY_MS);

    return () => {
      if (writeTimerRef.current !== null) {
        window.clearTimeout(writeTimerRef.current);
        writeTimerRef.current = null;
      }
    };
  }, [persistedSnapshot, restoreApplied]);

  return {
    restoredSession,
    restoreState,
    restoreApplied,
    markRestoreApplied: () => setRestoreApplied(true),
  };
}
