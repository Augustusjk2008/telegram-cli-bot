import type { HtmlPreviewHandle } from "../utils/filePreview";
import type { FileReadResult, PluginOpenTarget, PluginRenderResult } from "../services/types";
import type { WorkbenchLayoutState } from "./workbenchLayout";

export type DesktopSidebarView = "files" | "search" | "outline" | "debug" | "git" | "plugins" | "settings";
export type WorkbenchActivityId = DesktopSidebarView;

export type PersistedTabContentPersistence = "none" | "clean_snapshot" | "dirty_snapshot";

export type PersistedWorkbenchTab = {
  path: string;
  dirty: boolean;
  /** Monotonic version replayed to the language-service document store. */
  documentVersion?: number;
  lastModifiedNs?: string;
  encoding?: string;
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
  nextTerminalCwd?: string;
};

export type ChatWorkbenchStatus = {
  agentId?: string;
  workingDir?: string;
  state: "idle" | "running" | "waiting" | "error";
  processing: boolean;
  elapsedSeconds?: number;
  lastError?: string;
};

export type DebugWorkbenchStatus = {
  phase: "idle" | "starting" | "running" | "paused" | "stopping" | "error";
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
  selectedTreePath?: string;
  activeTabPath: string;
  terminalOverrideCwd?: string;
  focusedPane?: FocusedWorkbenchPane;
  tabs: PersistedWorkbenchTab[];
};

export type DesktopPaneState = {
  sidebarCollapsed: boolean;
  editorCollapsed: boolean;
  terminalCollapsed: boolean;
  chatCollapsed: boolean;
  sidebarView: DesktopSidebarView;
  layout: WorkbenchLayoutState;
};

export const ACTIVITY_RAIL_WIDTH_PX = 48;
export const COLLAPSED_SIDEBAR_SIZE_PX = ACTIVITY_RAIL_WIDTH_PX;
export const PANE_RESIZER_SIZE_PX = 8;

export const DEFAULT_DESKTOP_PANE_STATE: DesktopPaneState = {
  sidebarCollapsed: false,
  editorCollapsed: false,
  terminalCollapsed: false,
  chatCollapsed: false,
  sidebarView: "files",
  // Same value as DEFAULT_WORKBENCH_LAYOUT; spelled out to keep this module free of runtime imports.
  layout: { activeTemplate: "classic", templates: {} },
};

export const WORKBENCH_SESSION_VERSION = 1;
export const WORKBENCH_SESSION_WRITE_DELAY_MS = 400;
export const WORKBENCH_CLEAN_TAB_SNAPSHOT_LIMIT_BYTES = 256 * 1024;
export const WORKBENCH_SNAPSHOT_TOTAL_LIMIT_BYTES = 3 * 1024 * 1024;
export const WORKBENCH_EXPANDED_PATH_RESTORE_LIMIT = 20;
export const WORKBENCH_HIGHLIGHT_DURATION_MS = 1200;
export const CLOSED_TAB_HISTORY_LIMIT = 10;

export function isDesktopSidebarView(value: unknown): value is DesktopSidebarView {
  return value === "files"
    || value === "search"
    || value === "outline"
    || value === "debug"
    || value === "git"
    || value === "plugins"
    || value === "settings";
}

export type EditorTab = {
  path: string;
  basename: string;
  content: string;
  documentVersion: number;
  savedContent: string;
  kind?: "file" | "file-preview" | "git-diff" | "plugin-view" | "external-source";
  filePreview?: FileReadResult;
  htmlPreview?: HtmlPreviewHandle | null;
  pluginTargets?: PluginOpenTarget[];
  pluginOpenTarget?: PluginOpenTarget;
  pluginView?: PluginRenderResult;
  pluginInput?: Record<string, unknown>;
  sourcePath?: string;
  /** Opaque server-issued identifier for an external dependency source. */
  sourceId?: string;
  /** Sanitized path shown to users; never sent back as a file path. */
  displayPath?: string;
  readOnly?: boolean;
  dirty: boolean;
  loading: boolean;
  saving: boolean;
  statusText: string;
  error: string;
  lastModifiedNs?: string;
  encoding?: string;
  cold: boolean;
  missing: boolean;
  contentPersistence: PersistedTabContentPersistence;
};

export type EditorRevealLocation = {
  path: string;
  line: number;
  column: number;
  requestId: string;
};
