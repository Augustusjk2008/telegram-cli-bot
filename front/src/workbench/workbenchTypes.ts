export type DesktopPaneKey = "files" | "editor" | "terminal" | "chat";

export type DesktopPaneState = {
  filesCollapsed: boolean;
  editorCollapsed: boolean;
  terminalCollapsed: boolean;
  chatCollapsed: boolean;
  filesWidthPx: number;
  chatWidthPx: number;
  editorHeightPx: number;
};

export const COLLAPSED_SIDEBAR_SIZE_PX = 72;
export const PANE_RESIZER_SIZE_PX = 8;
export const MIN_FILES_WIDTH_PX = 220;
export const MIN_CHAT_WIDTH_PX = 260;
export const MIN_EDITOR_HEIGHT_PX = 220;
export const MIN_TERMINAL_HEIGHT_PX = 160;
export const MIN_CENTER_WIDTH_PX = 480;
export const WORKBENCH_HORIZONTAL_PADDING_PX = 24;

export const DEFAULT_DESKTOP_PANE_STATE: DesktopPaneState = {
  filesCollapsed: false,
  editorCollapsed: false,
  terminalCollapsed: false,
  chatCollapsed: false,
  filesWidthPx: 320,
  chatWidthPx: 384,
  editorHeightPx: 420,
};

type ClampPaneStateOptions = {
  containerWidthPx?: number;
  containerHeightPx?: number;
};

export function clampPaneState(
  state: DesktopPaneState,
  { containerWidthPx = 1440, containerHeightPx = 900 }: ClampPaneStateOptions = {},
): DesktopPaneState {
  const availableSidebarWidthPx = Math.max(
    MIN_FILES_WIDTH_PX + MIN_CHAT_WIDTH_PX,
    containerWidthPx - WORKBENCH_HORIZONTAL_PADDING_PX - MIN_CENTER_WIDTH_PX - PANE_RESIZER_SIZE_PX * 2,
  );

  let filesWidthPx = Math.max(MIN_FILES_WIDTH_PX, state.filesWidthPx);
  let chatWidthPx = Math.max(MIN_CHAT_WIDTH_PX, state.chatWidthPx);

  if (filesWidthPx + chatWidthPx > availableSidebarWidthPx) {
    chatWidthPx = MIN_CHAT_WIDTH_PX;
    filesWidthPx = Math.min(filesWidthPx, availableSidebarWidthPx - chatWidthPx);

    if (filesWidthPx < MIN_FILES_WIDTH_PX) {
      filesWidthPx = MIN_FILES_WIDTH_PX;
      chatWidthPx = Math.max(MIN_CHAT_WIDTH_PX, availableSidebarWidthPx - filesWidthPx);
    }
  }

  const maxEditorHeightPx = Math.max(
    MIN_EDITOR_HEIGHT_PX,
    containerHeightPx - MIN_TERMINAL_HEIGHT_PX - PANE_RESIZER_SIZE_PX,
  );

  return {
    ...state,
    filesWidthPx,
    chatWidthPx,
    editorHeightPx: Math.min(Math.max(MIN_EDITOR_HEIGHT_PX, state.editorHeightPx), maxEditorHeightPx),
  };
}

export type EditorTab = {
  path: string;
  content: string;
  savedContent: string;
  dirty: boolean;
  loading: boolean;
  saving: boolean;
  statusText: string;
  error: string;
  lastModifiedNs?: string;
};
