import type { PluginRenderResult } from "../services/types";

export type DesktopSidebarView = "files" | "search" | "outline" | "debug" | "git" | "plugins" | "settings";

export type PersistedTabContentPersistence = "none" | "clean_snapshot" | "dirty_snapshot";

export type PersistedWorkbenchTab = {
  path: string;
  dirty: boolean;
  lastModifiedNs?: string;
  savedContent?: string;
  draftContent?: string;
  contentPersistence: PersistedTabContentPersistence;
};

export type FocusedWorkbenchPane = "sidebar" | "editor" | "terminal" | "chat" | null;

export type WorkbenchRestoreState = "clean" | "restored" | "draft-only";

export type TerminalOverrideState = {
  cwd: string;
  source: "tree" | "manual";
};

export type TerminalWorkbenchStatus = {
  connected: boolean;
  connectionText: string;
  currentCwd: string;
  overrideCwd?: string;
};

export type ChatWorkbenchStatus = {
  state: "idle" | "running" | "waiting" | "error";
  processing: boolean;
  elapsedSeconds?: number;
  lastError?: string;
};

export type DebugWorkbenchStatus = {
  phase: "idle" | "preparing" | "deploying" | "starting_gdb" | "connecting_remote" | "paused" | "running" | "terminating" | "error";
  connectionText: string;
  targetText?: string;
  currentSourcePath?: string;
  currentLine?: number;
};

export type PersistedWorkbenchSession = {
  version: 1;
  botAlias: string;
  workspaceRoot: string;
  sidebarView: DesktopSidebarView;
  expandedPaths: string[];
  activeTabPath: string;
  terminalOverrideCwd?: string;
  focusedPane?: FocusedWorkbenchPane;
  tabs: PersistedWorkbenchTab[];
};

export type DesktopPaneState = {
  sidebarCollapsed: boolean;
  terminalCollapsed: boolean;
  chatCollapsed: boolean;
  sidebarView: DesktopSidebarView;
  sidebarWidthPx: number;
  chatWidthPx: number;
  editorHeightPx: number;
};

export const ACTIVITY_RAIL_WIDTH_PX = 48;
export const COLLAPSED_SIDEBAR_SIZE_PX = ACTIVITY_RAIL_WIDTH_PX;
export const PANE_RESIZER_SIZE_PX = 8;
export const MIN_SIDEBAR_WIDTH_PX = 220;
export const MIN_CHAT_WIDTH_PX = 260;
export const MIN_EDITOR_HEIGHT_PX = 220;
export const MIN_TERMINAL_HEIGHT_PX = 160;
export const MIN_CENTER_WIDTH_PX = 480;
export const WORKBENCH_HORIZONTAL_PADDING_PX = 4;

export const DEFAULT_DESKTOP_PANE_STATE: DesktopPaneState = {
  sidebarCollapsed: false,
  terminalCollapsed: false,
  chatCollapsed: false,
  sidebarView: "files",
  sidebarWidthPx: 320,
  chatWidthPx: 384,
  editorHeightPx: 420,
};

export const WORKBENCH_SESSION_VERSION = 1;
export const WORKBENCH_SESSION_WRITE_DELAY_MS = 400;
export const WORKBENCH_CLEAN_TAB_SNAPSHOT_LIMIT_BYTES = 256 * 1024;
export const WORKBENCH_SNAPSHOT_TOTAL_LIMIT_BYTES = 3 * 1024 * 1024;
export const WORKBENCH_EXPANDED_PATH_RESTORE_LIMIT = 20;
export const WORKBENCH_HIGHLIGHT_DURATION_MS = 1200;
export const CLOSED_TAB_HISTORY_LIMIT = 10;

type ClampPaneStateOptions = {
  containerWidthPx?: number;
  containerHeightPx?: number;
};

export function isDesktopSidebarView(value: unknown): value is DesktopSidebarView {
  return value === "files"
    || value === "search"
    || value === "outline"
    || value === "debug"
    || value === "git"
    || value === "plugins"
    || value === "settings";
}

export function clampPaneState(
  state: DesktopPaneState,
  { containerWidthPx = 1440, containerHeightPx = 900 }: ClampPaneStateOptions = {},
): DesktopPaneState {
  const availableSidebarWidthPx = Math.max(
    MIN_SIDEBAR_WIDTH_PX + MIN_CHAT_WIDTH_PX,
    containerWidthPx - WORKBENCH_HORIZONTAL_PADDING_PX - MIN_CENTER_WIDTH_PX - PANE_RESIZER_SIZE_PX * 2,
  );

  let sidebarWidthPx = Math.max(MIN_SIDEBAR_WIDTH_PX, state.sidebarWidthPx);
  let chatWidthPx = Math.max(MIN_CHAT_WIDTH_PX, state.chatWidthPx);

  if (sidebarWidthPx + chatWidthPx > availableSidebarWidthPx) {
    chatWidthPx = MIN_CHAT_WIDTH_PX;
    sidebarWidthPx = Math.min(sidebarWidthPx, availableSidebarWidthPx - chatWidthPx);

    if (sidebarWidthPx < MIN_SIDEBAR_WIDTH_PX) {
      sidebarWidthPx = MIN_SIDEBAR_WIDTH_PX;
      chatWidthPx = Math.max(MIN_CHAT_WIDTH_PX, availableSidebarWidthPx - sidebarWidthPx);
    }
  }

  const maxEditorHeightPx = Math.max(
    MIN_EDITOR_HEIGHT_PX,
    containerHeightPx - MIN_TERMINAL_HEIGHT_PX - PANE_RESIZER_SIZE_PX,
  );

  return {
    ...state,
    sidebarWidthPx,
    chatWidthPx,
    editorHeightPx: Math.min(Math.max(MIN_EDITOR_HEIGHT_PX, state.editorHeightPx), maxEditorHeightPx),
  };
}

export type EditorTab = {
  path: string;
  basename: string;
  content: string;
  savedContent: string;
  kind?: "file" | "git-diff" | "plugin-view";
  pluginView?: PluginRenderResult;
  pluginInput?: Record<string, unknown>;
  sourcePath?: string;
  readOnly?: boolean;
  dirty: boolean;
  loading: boolean;
  saving: boolean;
  statusText: string;
  error: string;
  lastModifiedNs?: string;
  cold: boolean;
  missing: boolean;
  contentPersistence: PersistedTabContentPersistence;
};
