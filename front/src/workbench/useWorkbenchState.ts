import { useEffect, useState } from "react";
import {
  DEFAULT_DESKTOP_PANE_STATE,
  type DesktopPaneState,
  type DesktopSidebarView,
} from "./workbenchTypes";
import {
  applyLayoutResize,
  normalizeWorkbenchLayout,
  resetLayoutTemplate as resetTemplateLayout,
  selectLayoutTemplate as selectTemplateLayout,
  serializeWorkbenchLayout,
  swapLayoutPanes as swapTemplatePanes,
  type LayoutTemplateId,
  type ResolvedLayoutResizer,
  type WorkbenchLayoutState,
  type WorkbenchPaneId,
} from "./workbenchLayout";

export const WORKBENCH_PANE_STATE_STORAGE_KEY = "web-workbench-pane-state";

function normalizeStoredPaneState(raw: unknown): DesktopPaneState {
  if (!raw || typeof raw !== "object") {
    return DEFAULT_DESKTOP_PANE_STATE;
  }

  const candidate = raw as Record<string, unknown>;
  return {
    sidebarCollapsed: typeof candidate.sidebarCollapsed === "boolean"
      ? candidate.sidebarCollapsed
      : typeof candidate.filesCollapsed === "boolean"
        ? candidate.filesCollapsed
        : DEFAULT_DESKTOP_PANE_STATE.sidebarCollapsed,
    editorCollapsed: typeof candidate.editorCollapsed === "boolean"
      ? candidate.editorCollapsed
      : DEFAULT_DESKTOP_PANE_STATE.editorCollapsed,
    terminalCollapsed: typeof candidate.terminalCollapsed === "boolean"
      ? candidate.terminalCollapsed
      : DEFAULT_DESKTOP_PANE_STATE.terminalCollapsed,
    chatCollapsed: typeof candidate.chatCollapsed === "boolean"
      ? candidate.chatCollapsed
      : DEFAULT_DESKTOP_PANE_STATE.chatCollapsed,
    sidebarView: DEFAULT_DESKTOP_PANE_STATE.sidebarView,
    layout: normalizeWorkbenchLayout(candidate),
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
      const { sidebarView: _sidebarView, layout, ...collapsedFlags } = paneState;
      localStorage.setItem(
        WORKBENCH_PANE_STATE_STORAGE_KEY,
        JSON.stringify({ ...collapsedFlags, ...serializeWorkbenchLayout(layout) }),
      );
    } catch {
      // Ignore storage failures and keep the in-memory state.
    }
  }, [paneState]);

  function updateLayout(update: (layout: WorkbenchLayoutState) => WorkbenchLayoutState) {
    setPaneState((current) => {
      const layout = update(current.layout);
      return layout === current.layout ? current : { ...current, layout };
    });
  }

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

  function toggleEditor() {
    setPaneState((current) => ({
      ...current,
      editorCollapsed: !current.editorCollapsed,
    }));
  }

  function showEditor() {
    setPaneState((current) => (current.editorCollapsed ? { ...current, editorCollapsed: false } : current));
  }

  function toggleChat() {
    setPaneState((current) => ({
      ...current,
      chatCollapsed: !current.chatCollapsed,
    }));
  }

  function showChat() {
    setPaneState((current) => (current.chatCollapsed ? { ...current, chatCollapsed: false } : current));
  }

  function setSidebarView(sidebarView: DesktopSidebarView) {
    setPaneState((current) => ({
      ...current,
      sidebarView,
      sidebarCollapsed: false,
    }));
  }

  function restoreSidebarView(sidebarView: DesktopSidebarView) {
    setPaneState((current) => ({
      ...current,
      sidebarView,
    }));
  }

  /** `resizer` is the descriptor captured at drag start and `deltaPx` is measured from there. */
  function resizeLayout(resizer: ResolvedLayoutResizer, deltaPx: number) {
    updateLayout((layout) => applyLayoutResize(layout, resizer, deltaPx));
  }

  function selectLayoutTemplate(id: LayoutTemplateId) {
    updateLayout((layout) => selectTemplateLayout(layout, id));
  }

  function swapLayoutPanes(a: WorkbenchPaneId, b: WorkbenchPaneId) {
    updateLayout((layout) => swapTemplatePanes(layout, a, b));
  }

  function resetLayoutTemplate() {
    updateLayout(resetTemplateLayout);
  }

  return {
    paneState,
    toggleSidebar,
    toggleEditor,
    toggleTerminal,
    toggleChat,
    showEditor,
    showChat,
    setSidebarView,
    restoreSidebarView,
    resizeLayout,
    selectLayoutTemplate,
    swapLayoutPanes,
    resetLayoutTemplate,
  };
}
