export type DesktopSidebarView = "files" | "git" | "settings";

export type DesktopPaneState = {
  sidebarCollapsed: boolean;
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
export const WORKBENCH_HORIZONTAL_PADDING_PX = 24;

export const DEFAULT_DESKTOP_PANE_STATE: DesktopPaneState = {
  sidebarCollapsed: false,
  sidebarView: "files",
  sidebarWidthPx: 320,
  chatWidthPx: 384,
  editorHeightPx: 420,
};

type ClampPaneStateOptions = {
  containerWidthPx?: number;
  containerHeightPx?: number;
};

export function isDesktopSidebarView(value: unknown): value is DesktopSidebarView {
  return value === "files" || value === "git" || value === "settings";
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
  content: string;
  savedContent: string;
  dirty: boolean;
  loading: boolean;
  saving: boolean;
  statusText: string;
  error: string;
  lastModifiedNs?: string;
};
