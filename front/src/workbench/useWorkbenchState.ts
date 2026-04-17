import { useEffect, useState } from "react";
import { DEFAULT_DESKTOP_PANE_STATE, type DesktopPaneKey, type DesktopPaneState } from "./workbenchTypes";

export const WORKBENCH_PANE_STATE_STORAGE_KEY = "web-workbench-pane-state";

function readStoredPaneState(): DesktopPaneState {
  try {
    const raw = localStorage.getItem(WORKBENCH_PANE_STATE_STORAGE_KEY);
    if (!raw) {
      return DEFAULT_DESKTOP_PANE_STATE;
    }
    return {
      ...DEFAULT_DESKTOP_PANE_STATE,
      ...JSON.parse(raw),
    };
  } catch {
    return DEFAULT_DESKTOP_PANE_STATE;
  }
}

export function useWorkbenchState() {
  const [paneState, setPaneState] = useState<DesktopPaneState>(() => readStoredPaneState());

  useEffect(() => {
    try {
      localStorage.setItem(WORKBENCH_PANE_STATE_STORAGE_KEY, JSON.stringify(paneState));
    } catch {
      // Ignore storage failures and keep the in-memory state.
    }
  }, [paneState]);

  function togglePane(key: DesktopPaneKey) {
    setPaneState((current) => {
      if (key === "files") {
        return { ...current, filesCollapsed: !current.filesCollapsed };
      }
      if (key === "editor") {
        return { ...current, editorCollapsed: !current.editorCollapsed };
      }
      if (key === "terminal") {
        return { ...current, terminalCollapsed: !current.terminalCollapsed };
      }
      return { ...current, chatCollapsed: !current.chatCollapsed };
    });
  }

  return {
    paneState,
    togglePane,
  };
}
