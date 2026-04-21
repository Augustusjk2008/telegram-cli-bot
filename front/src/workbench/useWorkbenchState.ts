import { useEffect, useState } from "react";
import {
  clampPaneState,
  DEFAULT_DESKTOP_PANE_STATE,
  isDesktopSidebarView,
  type DesktopPaneState,
  type DesktopSidebarView,
} from "./workbenchTypes";

export const WORKBENCH_PANE_STATE_STORAGE_KEY = "web-workbench-pane-state";

function toNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function normalizeStoredPaneState(raw: unknown): DesktopPaneState {
  if (!raw || typeof raw !== "object") {
    return DEFAULT_DESKTOP_PANE_STATE;
  }

  const candidate = raw as Record<string, unknown>;
  const sidebarView = isDesktopSidebarView(candidate.sidebarView)
    ? candidate.sidebarView
    : DEFAULT_DESKTOP_PANE_STATE.sidebarView;

  return {
    sidebarCollapsed: typeof candidate.sidebarCollapsed === "boolean"
      ? candidate.sidebarCollapsed
      : typeof candidate.filesCollapsed === "boolean"
        ? candidate.filesCollapsed
        : DEFAULT_DESKTOP_PANE_STATE.sidebarCollapsed,
    terminalCollapsed: typeof candidate.terminalCollapsed === "boolean"
      ? candidate.terminalCollapsed
      : DEFAULT_DESKTOP_PANE_STATE.terminalCollapsed,
    chatCollapsed: typeof candidate.chatCollapsed === "boolean"
      ? candidate.chatCollapsed
      : DEFAULT_DESKTOP_PANE_STATE.chatCollapsed,
    sidebarView,
    sidebarWidthPx: toNumber(candidate.sidebarWidthPx, toNumber(candidate.filesWidthPx, DEFAULT_DESKTOP_PANE_STATE.sidebarWidthPx)),
    chatWidthPx: toNumber(candidate.chatWidthPx, DEFAULT_DESKTOP_PANE_STATE.chatWidthPx),
    editorHeightPx: toNumber(candidate.editorHeightPx, DEFAULT_DESKTOP_PANE_STATE.editorHeightPx),
  };
}

function readStoredPaneState(): DesktopPaneState {
  try {
    const raw = localStorage.getItem(WORKBENCH_PANE_STATE_STORAGE_KEY);
    if (!raw) {
      return DEFAULT_DESKTOP_PANE_STATE;
    }
    return normalizeStoredPaneState(JSON.parse(raw));
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

  function toggleSidebar() {
    setPaneState((current) => ({
      ...current,
      sidebarCollapsed: !current.sidebarCollapsed,
    }));
  }

  function toggleTerminal() {
    setPaneState((current) => ({
      ...current,
      terminalCollapsed: !current.terminalCollapsed,
    }));
  }

  function toggleChat() {
    setPaneState((current) => ({
      ...current,
      chatCollapsed: !current.chatCollapsed,
    }));
  }

  function setSidebarView(sidebarView: DesktopSidebarView) {
    setPaneState((current) => ({
      ...current,
      sidebarView,
      sidebarCollapsed: false,
    }));
  }

  function resizePane(
    key: "sidebarWidthPx" | "chatWidthPx" | "editorHeightPx",
    nextValue: number,
    options?: { containerWidthPx?: number; containerHeightPx?: number },
  ) {
    setPaneState((current) => ({
      ...clampPaneState(
        {
          ...current,
          [key]: nextValue,
        },
        options,
      ),
    }));
  }

  return {
    paneState,
    toggleSidebar,
    toggleTerminal,
    toggleChat,
    setSidebarView,
    resizePane,
  };
}
