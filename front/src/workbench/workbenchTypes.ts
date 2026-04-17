export type DesktopPaneKey = "files" | "editor" | "terminal" | "chat";

export type DesktopPaneState = {
  filesCollapsed: boolean;
  editorCollapsed: boolean;
  terminalCollapsed: boolean;
  chatCollapsed: boolean;
};

export const DEFAULT_DESKTOP_PANE_STATE: DesktopPaneState = {
  filesCollapsed: false,
  editorCollapsed: false,
  terminalCollapsed: false,
  chatCollapsed: false,
};

export type EditorTab = {
  path: string;
  content: string;
  savedContent: string;
  dirty: boolean;
  loading: boolean;
  saving: boolean;
  statusText: string;
  error: string;
  lastModifiedNs?: number;
};
