import { clsx } from "clsx";
import { Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import type { ViewMode } from "../app/layoutMode";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { CodeLocation, CodeNavigationIntent, CodeNavigationKind, FileReadResult, GitTreeStatus, HostEffect, PluginOpenTarget } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import "../styles/workbench.css";
import type {
  ChatBodyFontFamilyName,
  ChatBodyFontSizeName,
  ChatBodyLineHeightName,
  ChatBodyParagraphSpacingName,
  UiThemeName,
} from "../theme";
import {
  isHtmlPreviewPath,
  isFilePreviewFullyLoaded,
  shouldAutoLoadFullHtmlPreview,
  withDetectedPreviewKind,
} from "../utils/filePreview";
import { WORKSPACE_DELETED_EVENT, isWorkspaceDeletedEvent } from "../utils/workspaceEvents";
import { inferFileEditorLanguageId } from "../utils/fileEditorLanguage";
import { ChatPane } from "./ChatPane";
import { CommandPalette } from "./CommandPalette";
import { FileTreePane } from "./FileTreePane";
import { LanChatDock } from "./LanChatDock";
import { OutlinePane } from "./OutlinePane";
import { PaneResizer } from "./PaneResizer";
import { SearchPane } from "./SearchPane";
import { WorkbenchActivityRail } from "./WorkbenchActivityRail";
import { WorkbenchHeader } from "./WorkbenchHeader";
import { WorkbenchStatusBar } from "./WorkbenchStatusBar";
import {
  LazyDebugPane as DebugPane,
  LazyEditorPane as EditorPane,
  LazyGitScreen as GitScreen,
  LazyPluginsScreen as PluginsScreen,
  LazySettingsScreen as SettingsScreen,
  LazyTerminalPane as TerminalPane,
} from "./lazyPanes";
import { useDebugSession } from "./useDebugSession";
import {
  useCodeNavigationHistory,
  type CodeNavigationHistoryLocation,
} from "./useCodeNavigationHistory";
import { useEditorTabs } from "./useEditorTabs";
import { useFileTree } from "./useFileTree";
import { useLanguageServerStatus } from "./useLanguageServerStatus";
import { useWorkbenchSession } from "./useWorkbenchSession";
import { useWorkbenchState } from "./useWorkbenchState";
import { toWorkspaceRelativeSourcePath } from "./debugSourcePath";
import {
  clampPaneState,
  COLLAPSED_SIDEBAR_SIZE_PX,
  MIN_TERMINAL_HEIGHT_PX,
  PANE_RESIZER_SIZE_PX,
  type ChatWorkbenchStatus,
  type EditorRevealLocation,
  type FocusedWorkbenchPane,
  type TerminalOverrideState,
  type TerminalWorkbenchStatus,
  type WorkbenchActivityId,
  type WorkbenchProductMode,
} from "./workbenchTypes";

const RASTER_IMAGE_PREVIEW_RE = /\.(?:png|jpe?g|gif|webp)$/i;
const paneFallback = (
  <div className="flex h-full min-h-[120px] items-center justify-center text-xs text-[var(--muted)]">
    正在加载...
  </div>
);

function normalizeWorkbenchPath(value: string) {
  return String(value || "").replace(/\\/g, "/").replace(/\/+$/, "");
}

function normalizeWorkbenchPathForCompare(value: string) {
  const normalized = normalizeWorkbenchPath(value);
  return /^[a-z]:/i.test(normalized) ? normalized.toLowerCase() : normalized;
}

function resolveRepoRelativeDiffPath(path: string, absolutePath: string, repoPath: string) {
  const normalizedRepoPath = normalizeWorkbenchPath(repoPath);
  const normalizedAbsolutePath = normalizeWorkbenchPath(absolutePath);
  if (!normalizedRepoPath || !normalizedAbsolutePath) {
    return path;
  }

  const repoKey = normalizedRepoPath.toLowerCase();
  const absoluteKey = normalizedAbsolutePath.toLowerCase();
  if (!absoluteKey.startsWith(`${repoKey}/`)) {
    return path;
  }

  const relativePath = normalizedAbsolutePath.slice(normalizedRepoPath.length + 1);
  return relativePath || path;
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

function formatDownloadProgress(downloadedBytes: number, totalBytes?: number) {
  if (typeof totalBytes === "number" && totalBytes > 0) {
    return `${formatBytes(downloadedBytes)} / ${formatBytes(totalBytes)}`;
  }
  return formatBytes(downloadedBytes);
}

type Props = {
  authToken?: string;
  accountId?: string;
  botAlias: string;
  client?: WebBotClient;
  structureOnly?: boolean;
  canWriteFiles?: boolean;
  canOpenSystemFolder?: boolean;
  canUseInlineCompletion?: boolean;
  chatReadOnly?: boolean;
  chatReadOnlyReason?: string;
  chatDisabledReason?: string;
  botCanOperate?: boolean;
  terminalDisabledReason?: string;
  allowTrace?: boolean;
  allowCodeJump?: boolean;
  themeName?: UiThemeName;
  onThemeChange?: (themeName: UiThemeName) => void;
  chatBodyFontFamily?: ChatBodyFontFamilyName;
  onChatBodyFontFamilyChange?: (fontFamily: ChatBodyFontFamilyName) => void;
  chatBodyFontSize?: ChatBodyFontSizeName;
  onChatBodyFontSizeChange?: (fontSize: ChatBodyFontSizeName) => void;
  chatBodyLineHeight?: ChatBodyLineHeightName;
  onChatBodyLineHeightChange?: (lineHeight: ChatBodyLineHeightName) => void;
  chatBodyParagraphSpacing?: ChatBodyParagraphSpacingName;
  onChatBodyParagraphSpacingChange?: (paragraphSpacing: ChatBodyParagraphSpacingName) => void;
  sessionCapabilities?: string[];
  viewMode?: ViewMode;
  hasUnreadOtherBots?: boolean;
  announcementAction?: ReactNode;
  chatPaneContent?: ReactNode | ((actions: { requestPreview: (path: string) => void }) => ReactNode);
  chatStatus?: ChatWorkbenchStatus;
  productMode?: WorkbenchProductMode;
  soloAvailable?: boolean;
  onUnreadResult?: (botAlias: string) => void;
  onProductModeChange?: (mode: WorkbenchProductMode) => void;
  onViewModeChange?: (viewMode: ViewMode) => void;
  onOpenBotSwitcher?: (anchorRect?: DOMRect) => void;
  onOpenBotManager?: () => void;
  onLogout?: () => void;
  onDirtyTabsChange?: (hasDirtyTabs: boolean) => void;
  onChatPaneVisibilityChange?: (visible: boolean) => void;
};

export function DesktopWorkbench({
  authToken = "",
  accountId,
  client = new MockWebBotClient(),
  botAlias,
  structureOnly = false,
  canWriteFiles = true,
  canOpenSystemFolder = false,
  canUseInlineCompletion = false,
  chatReadOnly = false,
  chatReadOnlyReason,
  chatDisabledReason,
  botCanOperate = true,
  terminalDisabledReason = "",
  allowTrace = true,
  allowCodeJump = true,
  themeName,
  onThemeChange,
  chatBodyFontFamily,
  onChatBodyFontFamilyChange,
  chatBodyFontSize,
  onChatBodyFontSizeChange,
  chatBodyLineHeight,
  onChatBodyLineHeightChange,
  chatBodyParagraphSpacing,
  onChatBodyParagraphSpacingChange,
  sessionCapabilities = [],
  viewMode = "desktop",
  hasUnreadOtherBots = false,
  announcementAction,
  chatPaneContent,
  chatStatus: externalChatStatus,
  productMode,
  soloAvailable = false,
  onUnreadResult,
  onProductModeChange,
  onViewModeChange,
  onOpenBotSwitcher,
  onOpenBotManager,
  onLogout,
  onDirtyTabsChange,
  onChatPaneVisibilityChange,
}: Props) {
  const { paneState, toggleSidebar, toggleTerminal, toggleChat, setSidebarView, restoreSidebarView, resizePane } = useWorkbenchState();
  const fileTree = useFileTree(botAlias, client, { structureOnly });
  const codeNavigationScope = `${botAlias}\n${fileTree.rootPath}`;
  const tabs = useEditorTabs({ botAlias, client, scopeKey: fileTree.rootPath, structureOnly, canWriteFiles });
  const columnsRef = useRef<HTMLDivElement | null>(null);
  const centerRowsRef = useRef<HTMLDivElement | null>(null);
  const editorPaneRef = useRef<HTMLElement | null>(null);
  const restoringRef = useRef(false);
  const previousBotAliasRef = useRef(botAlias);
  const previousWorkspaceRootRef = useRef("");
  const [layoutBounds, setLayoutBounds] = useState({
    columnsWidthPx: 1440,
    centerHeightPx: 900,
  });
  const [editorPaneBounds, setEditorPaneBounds] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);
  const [pendingSidebarWorkdir, setPendingSidebarWorkdir] = useState("");
  const [previewName, setPreviewName] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewMode, setPreviewMode] = useState<"preview" | "full">("preview");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] = useState<FileReadResult | null>(null);
  const previewRequestSeqRef = useRef(0);
  const [focusedPane, setFocusedPane] = useState<FocusedWorkbenchPane>(null);
  const [isResizingPane, setIsResizingPane] = useState(false);
  const [terminalOverride, setTerminalOverride] = useState<TerminalOverrideState | null>(null);
  const [pendingTerminalOverride, setPendingTerminalOverride] = useState<TerminalOverrideState | null>(null);
  const [localChatStatus, setLocalChatStatus] = useState<ChatWorkbenchStatus>({
    state: "idle",
    processing: false,
  });
  const [terminalStatus, setTerminalStatus] = useState<TerminalWorkbenchStatus>({
    connected: false,
    connectionText: "未启动",
    currentCwd: "",
  });
  const [gitBranchName, setGitBranchName] = useState("");
  const [gitDecorations, setGitDecorations] = useState<GitTreeStatus["items"]>({});
  const [gitRepoPath, setGitRepoPath] = useState("");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [editorReveal, setEditorReveal] = useState<EditorRevealLocation | null>(null);
  const [editorNavigationCommand, setEditorNavigationCommand] = useState<{
    kind: "definition" | "implementation";
    requestId: string;
  } | null>(null);
  const [definitionCandidates, setDefinitionCandidates] = useState<CodeLocation[]>([]);
  const [definitionMessage, setDefinitionMessage] = useState("");
  const [definitionSource, setDefinitionSource] = useState("");
  const [languageServerCatalogRevision, setLanguageServerCatalogRevision] = useState(0);
  const gitDecorationRequestRef = useRef(0);
  const codeNavigationRequestRef = useRef(0);
  const codeNavigationAbortControllerRef = useRef<AbortController | null>(null);
  const codeNavigationScopeRef = useRef(codeNavigationScope);
  const editorRevealRequestRef = useRef(0);
  const editorNavigationCommandRef = useRef(0);
  const definitionSourceLocationRef = useRef<CodeNavigationHistoryLocation | null>(null);
  const definitionSourceScopeRef = useRef("");
  codeNavigationScopeRef.current = codeNavigationScope;
  const reduceMotion = useReducedMotion();
  const activeLanguageServicePath = tabs.activeTab?.kind === "file" ? tabs.activeTab.path : "";
  const languageService = useLanguageServerStatus(client, botAlias, activeLanguageServicePath, languageServerCatalogRevision);
  const canNavigateImplementation = Boolean(
    allowCodeJump
    && tabs.activeTab?.kind === "file"
    && languageService.status?.implementationSupported === true,
  );
  const refreshLanguageServerCatalogStatus = useCallback(() => {
    setLanguageServerCatalogRevision((current) => current + 1);
  }, []);

  useEffect(() => {
    clearDefinitionOverlay();
    return () => {
      codeNavigationRequestRef.current += 1;
      codeNavigationAbortControllerRef.current?.abort();
      codeNavigationAbortControllerRef.current = null;
    };
  }, [client, codeNavigationScope]);

  const codeNavigationHistory = useCodeNavigationHistory({
    scopeKey: `${botAlias}\n${fileTree.rootPath}`,
    onNavigate: (location) => {
      const scope = codeNavigationScopeRef.current;
      return openWorkspaceFile(
        location.path,
        location.line,
        location.column,
        "",
        () => codeNavigationScopeRef.current === scope,
      );
    },
  });

  const layoutState = clampPaneState(paneState, {
    containerWidthPx: layoutBounds.columnsWidthPx,
    containerHeightPx: layoutBounds.centerHeightPx,
  });
  const canViewPlugins = sessionCapabilities.includes("view_plugins");
  const canPreviewFiles = !structureOnly;
  const canMutateFiles = canPreviewFiles && canWriteFiles;
  const activeSidebarView = !canViewPlugins && layoutState.sidebarView === "plugins"
    ? "files"
    : layoutState.sidebarView;
  const activeActivityItem: WorkbenchActivityId = activeSidebarView;
  const debug = useDebugSession({
    authToken,
    botAlias,
    client,
    enabled: !structureOnly && layoutState.sidebarView === "debug",
    onRevealLocation: ({ sourcePath, line }) => {
      void openWorkspaceFile(toWorkspaceRelativeSourcePath(sourcePath, fileTree.rootPath), line || undefined);
    },
  });

  const session = useWorkbenchSession({
    botAlias,
    accountId,
    workspaceRoot: fileTree.rootPath,
    snapshot: fileTree.rootPath
      ? {
          sidebarView: layoutState.sidebarView,
          expandedPaths: fileTree.expandedPaths,
          selectedTreePath: fileTree.selectedPath,
          activeTabPath: tabs.activeTabPath,
          terminalOverrideCwd: terminalOverride?.cwd,
          focusedPane,
          tabs: tabs.buildPersistenceSnapshot(),
        }
      : null,
  });

  const showTerminalPane = !structureOnly && (focusedPane === "terminal" || (!focusedPane && !layoutState.terminalCollapsed));
  const showChatPane = focusedPane === "chat" || (!focusedPane && !layoutState.chatCollapsed);
  const columnTemplate = structureOnly
    ? focusedPane === "sidebar"
      ? "minmax(0, 1fr) 0px 0px 0px 0px"
      : focusedPane === "chat"
        ? "0px 0px 0px 0px minmax(0, 1fr)"
        : `${layoutState.sidebarCollapsed ? COLLAPSED_SIDEBAR_SIZE_PX : layoutState.sidebarWidthPx}px ${PANE_RESIZER_SIZE_PX}px 0px ${layoutState.chatCollapsed ? 0 : PANE_RESIZER_SIZE_PX}px ${layoutState.chatCollapsed ? 0 : layoutState.chatWidthPx}px`
    : focusedPane === "sidebar"
      ? "minmax(0, 1fr) 0px 0px 0px 0px"
      : focusedPane === "chat"
        ? "0px 0px 0px 0px minmax(0, 1fr)"
        : focusedPane === "editor" || focusedPane === "terminal"
          ? "0px 0px minmax(0, 1fr) 0px 0px"
          : `${layoutState.sidebarCollapsed ? COLLAPSED_SIDEBAR_SIZE_PX : layoutState.sidebarWidthPx}px ${PANE_RESIZER_SIZE_PX}px minmax(0, 1fr) ${layoutState.chatCollapsed ? 0 : PANE_RESIZER_SIZE_PX}px ${layoutState.chatCollapsed ? 0 : layoutState.chatWidthPx}px`;
  const centerRowTemplate = structureOnly
    ? "0px 0px 0px"
    : focusedPane === "editor"
      ? "minmax(0, 1fr) 0px 0px"
      : focusedPane === "terminal"
        ? `0px 0px minmax(${MIN_TERMINAL_HEIGHT_PX}px, 1fr)`
        : layoutState.terminalCollapsed
          ? "minmax(0, 1fr) 0px 0px"
          : `${layoutState.editorHeightPx}px ${PANE_RESIZER_SIZE_PX}px minmax(${MIN_TERMINAL_HEIGHT_PX}px, 1fr)`;
  const workspaceName = fileTree.rootPath.split(/[\\/]+/).filter(Boolean).pop() || fileTree.rootPath || "/";
  const previewStatusText = previewResult?.previewKind === "image"
    ? "已加载图片预览"
    : previewResult?.previewKind === "html"
      ? "已加载 HTML 预览"
      : isFilePreviewFullyLoaded(previewResult) ? "已加载全文" : "";
  const canLoadFull = canPreviewFiles && !isFilePreviewFullyLoaded(previewResult);
  const canEditPreview = canMutateFiles && previewResult?.previewKind !== "image";
  const previewDownloadProgress = fileTree.downloadProgress?.path === previewName ? fileTree.downloadProgress : null;
  const showSidebarContent = focusedPane === "sidebar" || !layoutState.sidebarCollapsed;
  const sidebarContentMotion = resolveMotionProps(premiumMotion.sidebarContent, reduceMotion);
  const dialogPanelMotion = resolveMotionProps(premiumMotion.dialogPanel, reduceMotion);
  const availableActivityItems: WorkbenchActivityId[] = structureOnly
    ? ["files"]
    : [
        "files",
        "search",
        "outline",
        "debug",
        "git",
        ...(canViewPlugins ? ["plugins" as const] : []),
        "settings",
      ];
  const activeEditorLine = tabs.activeTab
    ? debug.currentLineForPath(tabs.activeTab.path)
    : null;

  const refreshGitDecorations = useCallback(async () => {
    const requestId = gitDecorationRequestRef.current + 1;
    gitDecorationRequestRef.current = requestId;
    try {
      const next = await client.getGitTreeStatus(botAlias);
      if (gitDecorationRequestRef.current !== requestId) {
        return;
      }
      setGitDecorations(next.repoFound ? next.items : {});
      setGitRepoPath(next.repoFound ? next.repoPath || "" : "");
    } catch {
      if (gitDecorationRequestRef.current !== requestId) {
        return;
      }
      setGitDecorations({});
      setGitRepoPath("");
    }
  }, [botAlias, client]);

  const refreshWorkspaceChrome = useCallback(async (options?: { preserveExpandedPaths?: boolean; rootPath?: string; gitDelayMs?: number }) => {
    const nextRootPath = await fileTree.refreshTreeAndRoot({
      preserveExpandedPaths: options?.preserveExpandedPaths,
      rootPath: options?.rootPath,
    });
    await refreshGitDecorations();
    return nextRootPath;
  }, [fileTree, refreshGitDecorations]);

  useEffect(() => {
    const handleWorkspaceDeleted = (event: Event) => {
      if (!isWorkspaceDeletedEvent(event) || event.detail.botAlias !== botAlias) {
        return;
      }
      const deletedPath = normalizeWorkbenchPathForCompare(event.detail.workspacePath);
      const currentRootPath = normalizeWorkbenchPathForCompare(fileTree.rootPath);
      if (deletedPath && currentRootPath && deletedPath !== currentRootPath) {
        return;
      }
      void tabs.restoreFromSnapshot([], "");
      void refreshWorkspaceChrome({ preserveExpandedPaths: false }).catch(() => undefined);
    };
    window.addEventListener(WORKSPACE_DELETED_EVENT, handleWorkspaceDeleted);
    return () => window.removeEventListener(WORKSPACE_DELETED_EVENT, handleWorkspaceDeleted);
  }, [botAlias, fileTree.rootPath, refreshWorkspaceChrome, tabs]);

  useEffect(() => {
    onDirtyTabsChange?.(tabs.hasDirtyTabs);
  }, [onDirtyTabsChange, tabs.hasDirtyTabs]);

  useEffect(() => {
    onChatPaneVisibilityChange?.(showChatPane);
  }, [onChatPaneVisibilityChange, showChatPane]);

  useEffect(() => {
    const updateLayoutBounds = () => {
      const nextColumnsWidthPx = columnsRef.current?.getBoundingClientRect().width ?? 0;
      const nextCenterHeightPx = centerRowsRef.current?.getBoundingClientRect().height ?? 0;
      const nextEditorPaneRect = editorPaneRef.current?.getBoundingClientRect();

      setLayoutBounds((current) => ({
        columnsWidthPx: nextColumnsWidthPx > 0 ? nextColumnsWidthPx : current.columnsWidthPx,
        centerHeightPx: nextCenterHeightPx > 0 ? nextCenterHeightPx : current.centerHeightPx,
      }));

      if (nextEditorPaneRect && nextEditorPaneRect.width > 0 && nextEditorPaneRect.height > 0) {
        setEditorPaneBounds((current) => {
          const nextBounds = {
            left: nextEditorPaneRect.left,
            top: nextEditorPaneRect.top,
            width: nextEditorPaneRect.width,
            height: nextEditorPaneRect.height,
          };

          if (
            current
            && current.left === nextBounds.left
            && current.top === nextBounds.top
            && current.width === nextBounds.width
            && current.height === nextBounds.height
          ) {
            return current;
          }

          return nextBounds;
        });
      }
    };

    updateLayoutBounds();
    window.addEventListener("resize", updateLayoutBounds);
    return () => {
      window.removeEventListener("resize", updateLayoutBounds);
    };
  }, [focusedPane, layoutState.chatWidthPx, layoutState.editorHeightPx, layoutState.sidebarCollapsed, layoutState.sidebarWidthPx]);

  useEffect(() => {
    if (previousBotAliasRef.current === botAlias) {
      return;
    }
    previousBotAliasRef.current = botAlias;
    restoreSidebarView("files");
    setFocusedPane(null);
    setTerminalOverride(null);
    setPendingTerminalOverride(null);
    setPendingSidebarWorkdir("");
  }, [botAlias, restoreSidebarView]);

  useEffect(() => {
    if (!fileTree.rootPath) {
      return;
    }
    const previousWorkspaceRoot = previousWorkspaceRootRef.current;
    previousWorkspaceRootRef.current = fileTree.rootPath;
    if (!previousWorkspaceRoot || previousWorkspaceRoot === fileTree.rootPath) {
      return;
    }
    restoreSidebarView("files");
    setFocusedPane(null);
    setTerminalOverride(null);
    setPendingTerminalOverride(null);
    setPendingSidebarWorkdir("");
    void tabs.restoreFromSnapshot([], "");
  }, [fileTree.rootPath, restoreSidebarView, tabs]);

  useEffect(() => {
    if (!fileTree.rootPath || !session.restoreLoaded || session.restoreApplied || restoringRef.current) {
      return;
    }

    restoringRef.current = true;
    let cancelled = false;

    void (async () => {
      try {
        const restoredSession = session.restoredSession;
        if (restoredSession) {
          restoreSidebarView(restoredSession.sidebarView);
          setFocusedPane(restoredSession.focusedPane ?? null);
          setTerminalOverride(restoredSession.terminalOverrideCwd
            ? { cwd: restoredSession.terminalOverrideCwd, source: "manual" }
            : null);
          await fileTree.restoreExpandedPaths(restoredSession.expandedPaths);
          if (restoredSession.selectedTreePath) {
            fileTree.selectPath(restoredSession.selectedTreePath);
          }
          await tabs.restoreFromSnapshot(restoredSession.tabs, restoredSession.activeTabPath);
        }
      } finally {
        restoringRef.current = false;
        if (!cancelled) {
          session.markRestoreApplied();
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [fileTree.rootPath, session.restoreApplied, session.restoreLoaded, session.restoredSession]);

  useEffect(() => {
    if (!fileTree.rootPath) {
      setGitBranchName("");
      setGitDecorations({});
      setGitRepoPath("");
      return;
    }

    let cancelled = false;

    void client.getGitOverview(botAlias)
      .then((overview) => {
        if (!cancelled) {
          setGitBranchName(overview.repoFound ? overview.currentBranch : "");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setGitBranchName("");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [botAlias, client, fileTree.rootPath]);

  useEffect(() => {
    if (!fileTree.rootPath) {
      return;
    }
    void refreshGitDecorations();
  }, [fileTree.rootPath, refreshGitDecorations]);

  useEffect(() => {
    if (!terminalStatus.currentCwd && fileTree.rootPath) {
      setTerminalStatus((current) => ({
        ...current,
        currentCwd: fileTree.rootPath,
      }));
    }
  }, [fileTree.rootPath, terminalStatus.currentCwd]);

  useEffect(() => {
    if (structureOnly && layoutState.sidebarView !== "files") {
      setSidebarView("files");
    }
  }, [layoutState.sidebarView, setSidebarView, structureOnly]);


  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (structureOnly) {
        return;
      }
      if (codeNavigationHistory.handleShortcut(event)) {
        event.preventDefault();
        return;
      }
      const key = event.key.toLowerCase();
      const primary = event.ctrlKey || event.metaKey;
      if (!primary) {
        return;
      }
      if (!event.shiftKey && key === "p") {
        event.preventDefault();
        setCommandPaletteOpen(true);
        return;
      }
      if (event.shiftKey && key === "f") {
        event.preventDefault();
        setSidebarView("search");
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [codeNavigationHistory.handleShortcut, setSidebarView, structureOnly]);

  function toggleFocusedPane(nextPane: Exclude<FocusedWorkbenchPane, null>) {
    setFocusedPane((current) => current === nextPane ? null : nextPane);
  }

  function selectActivityItem(item: WorkbenchActivityId) {
    setSidebarView(item);
  }

  function closePreview() {
    setPreviewName("");
    setPreviewContent("");
    setPreviewResult(null);
  }

  function isRasterImagePath(path: string) {
    return RASTER_IMAGE_PREVIEW_RE.test(path);
  }

  const loadPreview = useCallback(async (path: string, mode: "preview" | "full") => {
    if (!canPreviewFiles) {
      return;
    }
    const requestSeq = previewRequestSeqRef.current + 1;
    previewRequestSeqRef.current = requestSeq;
    setPreviewLoading(true);
    try {
      let result = mode === "full"
        ? await client.readFileFull(botAlias, path)
        : await client.readFile(botAlias, path);
      if (mode === "preview" && shouldAutoLoadFullHtmlPreview(path, result)) {
        result = await client.readFileFull(botAlias, path);
      }
      if (requestSeq !== previewRequestSeqRef.current) {
        return;
      }
      result = withDetectedPreviewKind(path, result);
      setPreviewName(path);
      setPreviewMode(result.mode === "cat" ? "full" : "preview");
      setPreviewResult(result);
      setPreviewContent(result.previewKind === "image" ? "" : result.content || "文件为空");
    } finally {
      if (requestSeq === previewRequestSeqRef.current) {
        setPreviewLoading(false);
      }
    }
  }, [botAlias, canPreviewFiles, client]);

  const handleRequestPreview = useCallback((path: string) => {
    void loadPreview(path, "preview");
  }, [loadPreview]);

  const resolvedChatPaneContent = typeof chatPaneContent === "function"
    ? chatPaneContent({
        requestPreview: handleRequestPreview,
      })
    : chatPaneContent;

  async function openWorkspaceFile(
    path: string,
    line?: number,
    column = 1,
    requestId = "",
    isCurrent: () => boolean = () => true,
  ) {
    if (!isCurrent()) {
      return false;
    }
    const target = await client.resolveFileOpenTarget(botAlias, path);
    if (!isCurrent()) {
      return false;
    }
    if (!canPreviewFiles) {
      await fileTree.revealPath(path);
      if (!isCurrent()) return false;
      setEditorReveal(null);
      return false;
    }
    if (target.kind === "plugin_view") {
      await Promise.allSettled([
        tabs.openPluginView(target),
        fileTree.revealPath(path),
      ]);
      if (!isCurrent()) return false;
      setEditorReveal(null);
      return false;
    }
    if (isRasterImagePath(path) || isHtmlPreviewPath(path)) {
      await Promise.allSettled([
        loadPreview(path, "preview"),
        fileTree.revealPath(path),
      ]);
      if (!isCurrent()) return false;
      setEditorReveal(null);
      return false;
    }

    if (!canWriteFiles) {
      await Promise.allSettled([
        loadPreview(path, "preview"),
        fileTree.revealPath(path),
      ]);
      if (!isCurrent()) return false;
      setEditorReveal(null);
      return false;
    }

    await Promise.allSettled([
      tabs.openFile(path, target.pluginTargets),
      fileTree.revealPath(path),
    ]);
    if (!isCurrent()) {
      return false;
    }
    if (line && line > 0) {
      const revealRequestId = requestId || `editor-reveal-${++editorRevealRequestRef.current}`;
      setEditorReveal({ path, line, column: Math.max(1, column), requestId: revealRequestId });
      return true;
    }
    setEditorReveal(null);
    return true;
  }

  async function openGitDiffInEditor(path: string, staged: boolean, gitPath = path) {
    const diff = await client.getGitDiff(botAlias, gitPath, staged);
    const basename = path.split(/[\\/]/).filter(Boolean).pop() || path;
    const tabPath = `git-diff:${staged ? "staged" : "worktree"}:${gitPath}`;
    tabs.openReadOnlyTab({
      path: tabPath,
      basename: `${basename}.diff`,
      content: diff.truncated && diff.diff
        ? `${diff.diff}\n\n...[diff truncated]`
        : (diff.diff || "当前没有可显示的差异"),
      sourcePath: path,
      kind: "git-diff",
      statusText: `${path} · ${staged ? "已暂存" : "工作区"} Diff · 只读${diff.truncated ? " · 已截断" : ""}`,
    });
  }

  async function openPluginViewTab(target: PluginOpenTarget) {
    await tabs.openPluginView(target);
    const sourcePath = typeof target.input.path === "string" ? target.input.path : "";
    if (sourcePath) {
      setSidebarView("files");
      await fileTree.revealPath(sourcePath);
    }
  }

  async function runPluginHostEffects(effects: HostEffect[]) {
    for (const effect of effects) {
      if (effect.type === "open_file") {
        setSidebarView("files");
        await openWorkspaceFile(effect.path, effect.line);
        continue;
      }
      if (effect.type === "reveal_in_files") {
        setSidebarView("files");
        await fileTree.revealPath(effect.path);
        continue;
      }
      if (effect.type === "copy_text") {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(effect.text);
        }
        continue;
      }
      if (effect.type === "download_artifact") {
        await client.downloadPluginArtifact(botAlias, effect.artifactId, effect.filename);
        continue;
      }
      await openPluginViewTab(effect);
    }
  }

  function clearDefinitionOverlay() {
    setDefinitionCandidates([]);
    setDefinitionMessage("");
    setDefinitionSource("");
    definitionSourceLocationRef.current = null;
    definitionSourceScopeRef.current = "";
  }

  function requestEditorCodeNavigation(kind: CodeNavigationKind) {
    if (
      !allowCodeJump
      || structureOnly
      || tabs.activeTab?.kind !== "file"
      || (kind === "implementation" && !canNavigateImplementation)
    ) {
      return false;
    }
    setEditorNavigationCommand({
      kind,
      requestId: `editor-code-navigation-${++editorNavigationCommandRef.current}`,
    });
    return true;
  }

  async function openDefinitionCandidate(item: CodeLocation) {
    const source = definitionSourceLocationRef.current;
    const scope = definitionSourceScopeRef.current;
    const path = item.path || "";
    const target = {
      path,
      line: item.selectionRange.start.line,
      column: item.selectionRange.start.column,
    };
    clearDefinitionOverlay();
    if (!path || !scope || codeNavigationScopeRef.current !== scope) {
      return;
    }
    const opened = await openWorkspaceFile(
      path,
      target.line,
      target.column,
      "",
      () => codeNavigationScopeRef.current === scope,
    );
    if (opened && source && codeNavigationScopeRef.current === scope) {
      codeNavigationHistory.recordNavigation(source, target);
    }
  }

  async function handleResolveCodeNavigation(input: CodeNavigationIntent) {
    if (!allowCodeJump || structureOnly || (input.kind === "implementation" && !canNavigateImplementation)) {
      return;
    }
    const activeTab = tabs.activeTab;
    if (!activeTab || activeTab.kind !== "file" || activeTab.path !== input.path) {
      return;
    }
    const source = {
      path: input.path,
      line: input.line,
      column: input.column,
    };
    const sequence = codeNavigationRequestRef.current + 1;
    codeNavigationRequestRef.current = sequence;
    codeNavigationAbortControllerRef.current?.abort();
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    codeNavigationAbortControllerRef.current = controller;
    const scope = codeNavigationScopeRef.current;
    const isCurrent = () => (
      codeNavigationScopeRef.current === scope
      && codeNavigationRequestRef.current === sequence
      && !controller?.signal.aborted
    );
    const requestId = `code-navigation-${Date.now()}-${sequence}`;
    try {
      const result = await client.resolveCodeNavigation(botAlias, {
        kind: input.kind,
        requestId,
        document: {
          path: activeTab.path,
          languageId: inferFileEditorLanguageId(activeTab.path),
          version: sequence,
          content: activeTab.content,
        },
        position: { line: input.line, column: input.column },
      }, controller?.signal);
      if (!isCurrent()) {
        return;
      }
      const semanticItems = result.items.filter((item) => item.targetType === "workspace" && item.path);
      if (semanticItems.length === 1) {
        clearDefinitionOverlay();
        const item = semanticItems[0];
        const target = {
          path: item.path || "",
          line: item.selectionRange.start.line,
          column: item.selectionRange.start.column,
        };
        const opened = await openWorkspaceFile(
          target.path,
          target.line,
          target.column,
          result.requestId || requestId,
          isCurrent,
        );
        if (opened && isCurrent()) {
          codeNavigationHistory.recordNavigation(source, target);
        }
        return;
      }
      if (semanticItems.length > 1) {
        setDefinitionCandidates(semanticItems);
        setDefinitionMessage("");
        setDefinitionSource(input.symbol || `${input.path}:${input.line}:${input.column}`);
        definitionSourceLocationRef.current = source;
        definitionSourceScopeRef.current = scope;
        return;
      }
      setDefinitionCandidates([]);
      setDefinitionMessage(result.message || (input.kind === "implementation" ? "未找到语义实现" : "未找到语义定义"));
      setDefinitionSource(input.symbol || `${input.path}:${input.line}:${input.column}`);
      definitionSourceLocationRef.current = null;
    } catch (error) {
      if (
        controller?.signal.aborted
        || codeNavigationRequestRef.current !== sequence
        || (error as { name?: string })?.name === "AbortError"
      ) {
        return;
      }
      setDefinitionCandidates([]);
      setDefinitionMessage(error instanceof Error ? error.message : "代码导航失败");
      setDefinitionSource(input.symbol || `${input.path}:${input.line}:${input.column}`);
      definitionSourceLocationRef.current = null;
    } finally {
      if (codeNavigationAbortControllerRef.current === controller) {
        codeNavigationAbortControllerRef.current = null;
      }
    }
  }

  async function handleUpload(files: File[]) {
    if (!canMutateFiles) {
      return;
    }
    for (const file of files) {
      await client.uploadFile(botAlias, file);
      fileTree.highlightPath(file.name);
    }
    await refreshWorkspaceChrome({ preserveExpandedPaths: true });
  }

  async function handleFileTreeHome() {
    const workingDir = await client.getCurrentPath(botAlias);
    if (!structureOnly) {
      await client.changeDirectory(botAlias, workingDir);
    }
    await refreshWorkspaceChrome({ rootPath: workingDir });
  }

  async function handleOpenSystemFolder() {
    await client.openBotWorkdir(botAlias);
  }

  function renderSidebarContent() {
    if (structureOnly || activeSidebarView === "files") {
      return (
        <FileTreePane
          tree={fileTree}
          onOpenFile={(path) => {
            void openWorkspaceFile(path);
          }}
          onCreatedFile={(path, content, lastModifiedNs) => {
            tabs.openCreatedFile(path, content, lastModifiedNs);
            fileTree.highlightPath(path);
          }}
          onRenamedFile={(oldPath, nextPath) => {
            tabs.syncRenamedPath(oldPath, nextPath);
            fileTree.highlightPath(nextPath);
          }}
          onDeletedFile={(path) => {
            tabs.closePath(path);
          }}
          onRequestPreview={(path) => {
            void loadPreview(path, "preview");
          }}
          onRequestDiff={(path, absolutePath) => {
            const gitPath = resolveRepoRelativeDiffPath(path, absolutePath, gitRepoPath);
            void openGitDiffInEditor(path, false, gitPath);
          }}
          onRequestUpload={handleUpload}
          onRequestHome={handleFileTreeHome}
          onRequestOpenSystemFolder={canOpenSystemFolder ? handleOpenSystemFolder : undefined}
          gitDecorations={gitDecorations}
          onRefreshGitDecorations={refreshGitDecorations}
          onRequestSetWorkdir={(path) => {
            setPendingSidebarWorkdir(path);
            setSidebarView("settings");
          }}
          structureOnly={structureOnly}
          canWriteFiles={canWriteFiles}
          focused={focusedPane === "sidebar"}
          onToggleFocus={() => toggleFocusedPane("sidebar")}
        />
      );
    }

    if (activeSidebarView === "search") {
      return (
        <SearchPane
          botAlias={botAlias}
          client={client}
          onOpenFile={async (path, line) => {
            await openWorkspaceFile(path, line);
          }}
        />
      );
    }

    if (activeSidebarView === "outline") {
      return (
        <OutlinePane
          botAlias={botAlias}
          client={client}
          activeFilePath={tabs.activeTab?.path || ""}
          onOpenFile={async (path, line) => {
            await openWorkspaceFile(path, line);
          }}
        />
      );
    }

    if (activeSidebarView === "debug") {
      return (
        <Suspense fallback={paneFallback}>
        <DebugPane
          profile={debug.profile}
          profileLoading={debug.profileLoading}
          state={debug.state}
          prepareLogs={debug.prepareLogs}
          launchForm={debug.launchForm}
          onLaunchFormChange={debug.updateLaunchForm}
          onLaunch={() => {
            void debug.launch();
          }}
          onContinue={() => {
            void debug.continueExecution();
          }}
          onPause={() => {
            void debug.pauseExecution();
          }}
          onNext={() => {
            void debug.next();
          }}
          onStepIn={() => {
            void debug.stepIn();
          }}
          onStepOut={() => {
            void debug.stepOut();
          }}
          onStop={() => {
            void debug.stop();
          }}
          onSelectFrame={(frameId) => {
            void debug.selectFrame(frameId);
          }}
          onRequestVariables={(variablesReference) => {
            void debug.requestVariables(variablesReference);
          }}
        />
        </Suspense>
      );
    }

    if (activeSidebarView === "git") {
      return (
        <Suspense fallback={paneFallback}>
        <GitScreen
          botAlias={botAlias}
          client={client}
          embedded
          sessionCapabilities={sessionCapabilities}
          onOpenDiff={openGitDiffInEditor}
          onOverviewChange={(overview) => {
            setGitBranchName(overview?.repoFound ? overview.currentBranch : "");
            void refreshGitDecorations();
          }}
        />
        </Suspense>
      );
    }

    if (activeSidebarView === "plugins") {
      return (
        <Suspense fallback={paneFallback}>
        <PluginsScreen
          client={client}
          botAlias={botAlias}
          canOperate={botCanOperate}
          embedded
          onApplyHostEffects={runPluginHostEffects}
          onOpenPluginView={openPluginViewTab}
        />
        </Suspense>
      );
    }

    if (activeSidebarView === "settings") {
      return (
        <Suspense fallback={paneFallback}>
        <SettingsScreen
          botAlias={botAlias}
          client={client}
          onLogout={() => onLogout?.()}
          embedded
          prefilledWorkdir={pendingSidebarWorkdir || fileTree.rootPath}
          onWorkdirUpdated={(nextWorkdir) => {
            setPendingSidebarWorkdir(nextWorkdir);
            void refreshWorkspaceChrome({ preserveExpandedPaths: true, rootPath: nextWorkdir });
          }}
          themeName={themeName}
          onThemeChange={onThemeChange}
          chatBodyFontFamily={chatBodyFontFamily}
          onChatBodyFontFamilyChange={onChatBodyFontFamilyChange}
          chatBodyFontSize={chatBodyFontSize}
          onChatBodyFontSizeChange={onChatBodyFontSizeChange}
          chatBodyLineHeight={chatBodyLineHeight}
          onChatBodyLineHeightChange={onChatBodyLineHeightChange}
          chatBodyParagraphSpacing={chatBodyParagraphSpacing}
          onChatBodyParagraphSpacingChange={onChatBodyParagraphSpacingChange}
          sessionCapabilities={sessionCapabilities}
          showBotRuntimeSettings={false}
          onOpenBotManager={onOpenBotManager}
          onLanguageServerCatalogChanged={refreshLanguageServerCatalogStatus}
        />
        </Suspense>
      );
    }
  }

  const lanChatDock = (
    <LanChatDock
      client={client}
      visible={!structureOnly && !Boolean(focusedPane)}
    />
  );

  return (
    <div
      data-testid="desktop-workbench-root"
      data-restore-state={session.restoreState}
      data-has-focus={focusedPane ? "true" : "false"}
      data-focused-pane={focusedPane || "none"}
      data-resizing={isResizingPane ? "true" : "false"}
      className="desktop-workbench-root grid h-[100dvh] min-h-0 w-full grid-rows-[auto_minmax(0,1fr)_auto]"
    >
      {focusedPane ? (
        <button
          type="button"
          data-testid="workbench-focus-backdrop"
          aria-label="退出聚焦模式"
          onClick={() => setFocusedPane(null)}
          className="absolute inset-0 z-20 bg-black/45"
        />
      ) : null}

      <WorkbenchHeader
        currentBot={botAlias}
        workspaceName={workspaceName}
        branchName={gitBranchName}
        viewMode={viewMode}
        hasUnreadOtherBots={hasUnreadOtherBots}
        announcementAction={announcementAction}
        sidebarVisible={!layoutState.sidebarCollapsed}
        terminalVisible={!structureOnly && !layoutState.terminalCollapsed}
        chatVisible={!layoutState.chatCollapsed}
        availableLayoutControls={structureOnly ? ["sidebar", "chat"] : undefined}
        productMode={productMode}
        soloAvailable={soloAvailable}
        onProductModeChange={onProductModeChange}
        onToggleSidebar={toggleSidebar}
        onToggleTerminal={toggleTerminal}
        onToggleChat={toggleChat}
        onViewModeChange={(nextMode) => onViewModeChange?.(nextMode)}
        onOpenBotSwitcher={(anchorRect) => onOpenBotSwitcher?.(anchorRect)}
        onLogout={() => onLogout?.()}
      />

      <div data-testid="desktop-workbench-shell" className="min-h-0 overflow-hidden bg-[var(--workbench-titlebar-bg)]">
        <div
          data-testid="desktop-workbench-columns"
          ref={columnsRef}
          className="grid h-full min-h-0 p-0.5"
          style={{ gridTemplateColumns: columnTemplate }}
        >
          <section
            data-testid="desktop-pane-files"
            data-collapsed={layoutState.sidebarCollapsed ? "true" : "false"}
            data-focused={focusedPane === "sidebar" ? "true" : "false"}
            className="desktop-workbench-pane grid min-h-0 overflow-hidden"
          >
            <div
              className={clsx(
                "grid min-h-0",
                showSidebarContent ? "grid-cols-[48px_minmax(0,1fr)]" : "grid-cols-[48px]",
              )}
            >
              <WorkbenchActivityRail
                activeItem={activeActivityItem}
                sidebarCollapsed={layoutState.sidebarCollapsed}
                availableItems={availableActivityItems}
                onToggleSidebar={toggleSidebar}
                onSelectItem={selectActivityItem}
              />

              {showSidebarContent ? (
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div
                    key={activeSidebarView}
                    className="flex min-h-0 min-w-0 flex-1 flex-col"
                    {...sidebarContentMotion}
                  >
                    {layoutState.sidebarView === "files" ? (
                      renderSidebarContent()
                    ) : (
                      <div data-testid="desktop-sidebar-scroll" className="h-full min-h-0 flex-1 overflow-y-auto">
                        {renderSidebarContent()}
                      </div>
                    )}
                  </motion.div>
                </AnimatePresence>
              ) : null}
            </div>
          </section>

          <PaneResizer
            ariaLabel="调整文件区宽度"
            axis="x"
            onResizeStart={() => setIsResizingPane(true)}
            onResizeEnd={() => setIsResizingPane(false)}
            onResizeDelta={(deltaPx) =>
              resizePane("sidebarWidthPx", layoutState.sidebarWidthPx + deltaPx, {
                containerWidthPx: layoutBounds.columnsWidthPx,
                containerHeightPx: layoutBounds.centerHeightPx,
              })}
          />

          <div
            data-testid="desktop-workbench-center-rows"
            ref={centerRowsRef}
            className="grid min-h-0 overflow-hidden"
            style={{ gridTemplateRows: centerRowTemplate }}
          >
            {!structureOnly ? (
              <section
                data-testid="desktop-pane-editor"
                ref={editorPaneRef}
                data-focused={focusedPane === "editor" ? "true" : "false"}
                className="desktop-workbench-pane min-h-0 overflow-hidden"
              >
                <Suspense fallback={paneFallback}>
                <EditorPane
                  botAlias={botAlias}
                  client={client}
                  tabs={tabs.tabs}
                  activeTab={tabs.activeTab}
                  activeTabPath={tabs.activeTabPath}
                  breakpointLines={tabs.activeTab ? debug.breakpointLinesForPath(tabs.activeTab.path) : []}
                  currentLine={activeEditorLine}
                  editorReveal={editorReveal}
                  navigationCommand={editorNavigationCommand}
                  canNavigateBack={codeNavigationHistory.canGoBack}
                  canNavigateForward={codeNavigationHistory.canGoForward}
                  allowCodeJump={allowCodeJump}
                  canNavigateImplementation={canNavigateImplementation}
                  canUseInlineCompletion={canUseInlineCompletion}
                  onResolveCodeNavigation={(input) => {
                    setEditorNavigationCommand(null);
                    void handleResolveCodeNavigation(input);
                  }}
                  onNavigateBack={() => {
                    void codeNavigationHistory.goBack();
                  }}
                  onNavigateForward={() => {
                    void codeNavigationHistory.goForward();
                  }}
                  onToggleBreakpoint={tabs.activeTab
                    ? (line) => {
                        void debug.toggleBreakpoint(tabs.activeTab?.path || "", line);
                      }
                    : undefined}
                  onActivateTab={(path) => {
                    setEditorReveal(null);
                    void tabs.activateTab(path);
                  }}
                  onCloseTab={tabs.closeTab}
                  onChangeActiveContent={tabs.updateActiveContent}
                  onSaveActiveTab={() => void tabs.saveActiveTab()}
                  onCloseOthers={tabs.closeOtherTabs}
                  onCloseTabsToRight={tabs.closeTabsToRight}
                  onReopenLastClosed={() => {
                    void tabs.reopenLastClosedTab();
                  }}
                  onRevealInTree={(path) => {
                    setSidebarView("files");
                    void fileTree.revealPath(path);
                  }}
                  onApplyHostEffects={runPluginHostEffects}
                  onClosePluginTab={(path) => {
                    tabs.closePath(path);
                  }}
                  onReopenPluginView={(target) => {
                    void openPluginViewTab(target);
                  }}
                  focused={focusedPane === "editor"}
                  onToggleFocus={() => toggleFocusedPane("editor")}
                />
                </Suspense>
              </section>
            ) : null}

            {!structureOnly && !focusedPane && showTerminalPane ? (
              <PaneResizer
                ariaLabel="调整编辑器高度"
                axis="y"
                onResizeStart={() => setIsResizingPane(true)}
                onResizeEnd={() => setIsResizingPane(false)}
                onResizeDelta={(deltaPx) =>
                  resizePane("editorHeightPx", layoutState.editorHeightPx + deltaPx, {
                    containerWidthPx: layoutBounds.columnsWidthPx,
                    containerHeightPx: layoutBounds.centerHeightPx,
                  })}
              />
            ) : (
              <div aria-hidden="true" />
            )}

            {!structureOnly ? (
              <section
                data-testid="desktop-pane-terminal"
                data-collapsed={layoutState.terminalCollapsed ? "true" : "false"}
                data-focused={focusedPane === "terminal" ? "true" : "false"}
                className={clsx(
                  "desktop-workbench-pane min-h-0 overflow-hidden",
                  !showTerminalPane && "hidden",
                )}
              >
                <Suspense fallback={paneFallback}>
                <TerminalPane
                  authToken={authToken}
                  botAlias={botAlias}
                  client={client}
                  preferredWorkingDir={terminalOverride?.cwd || fileTree.rootPath}
                  pendingWorkingDir={pendingTerminalOverride?.cwd}
                  themeName={themeName}
                  disabledReason={terminalDisabledReason}
                  visible={showTerminalPane}
                  focused={focusedPane === "terminal"}
                  onToggleFocus={() => toggleFocusedPane("terminal")}
                  onWorkbenchStatusChange={setTerminalStatus}
                  onAcceptPendingWorkingDir={() => {
                    if (pendingTerminalOverride) {
                      setTerminalOverride(pendingTerminalOverride);
                    }
                    setPendingTerminalOverride(null);
                  }}
                  onCancelPendingWorkingDir={() => {
                    setPendingTerminalOverride(null);
                  }}
                />
                </Suspense>
              </section>
            ) : null}
          </div>

          {!focusedPane && showChatPane ? (
            <PaneResizer
              ariaLabel="调整聊天区宽度"
              axis="x"
              onResizeStart={() => setIsResizingPane(true)}
              onResizeEnd={() => setIsResizingPane(false)}
              onResizeDelta={(deltaPx) =>
                resizePane("chatWidthPx", layoutState.chatWidthPx - deltaPx, {
                  containerWidthPx: layoutBounds.columnsWidthPx,
                  containerHeightPx: layoutBounds.centerHeightPx,
                })}
            />
          ) : (
            <div aria-hidden="true" />
          )}

          <section
            data-testid="desktop-pane-chat"
            data-collapsed={layoutState.chatCollapsed ? "true" : "false"}
            data-focused={focusedPane === "chat" ? "true" : "false"}
            className={clsx(
              "desktop-workbench-pane min-h-0 overflow-hidden",
              !showChatPane && "hidden",
            )}
          >
            {resolvedChatPaneContent || (
              <ChatPane
                botAlias={botAlias}
                client={client}
                readOnly={chatReadOnly}
                readOnlyReason={chatReadOnlyReason}
                disabledReason={chatDisabledReason}
                allowTrace={allowTrace}
                visible={showChatPane}
                focused={focusedPane === "chat"}
                onToggleFocus={() => toggleFocusedPane("chat")}
                onUnreadResult={onUnreadResult}
                onWorkbenchStatusChange={setLocalChatStatus}
                onRequestDesktopPreview={handleRequestPreview}
              />
            )}
          </section>
        </div>
      </div>

      <WorkbenchStatusBar
        activeFilePath={tabs.activeTab?.path || ""}
        fileDirty={Boolean(tabs.activeTab?.dirty)}
        terminalStatus={terminalStatus}
        chatStatus={externalChatStatus || localChatStatus}
        debugStatus={debug.statusBar}
        restoreState={session.restoreState}
        branchName={gitBranchName}
        viewMode={viewMode}
        languageServiceProvider={languageService.provider}
        languageServiceStatus={languageService.status}
        languageServiceLoading={languageService.loading}
        rightAction={(
          <div className="flex items-center gap-2">
            {fileTree.downloadProgress ? (
              <span role="status" aria-label="下载进度" className="max-w-[18rem] truncate">
                下载 {fileTree.downloadProgress.path}
                {typeof fileTree.downloadProgress.percent === "number"
                  ? ` ${fileTree.downloadProgress.percent}%`
                  : ` ${formatDownloadProgress(fileTree.downloadProgress.downloadedBytes, fileTree.downloadProgress.totalBytes)}`}
              </span>
            ) : null}
            {lanChatDock}
          </div>
        )}
      />

      {!structureOnly ? (
        <CommandPalette
          open={commandPaletteOpen}
          botAlias={botAlias}
          client={client}
          disabled={structureOnly}
          canNavigateDefinition={allowCodeJump && tabs.activeTab?.kind === "file"}
          canNavigateImplementation={canNavigateImplementation}
          canNavigateBack={codeNavigationHistory.canGoBack}
          canNavigateForward={codeNavigationHistory.canGoForward}
          onNavigateDefinition={() => {
            requestEditorCodeNavigation("definition");
          }}
          onNavigateImplementation={() => {
            requestEditorCodeNavigation("implementation");
          }}
          onNavigateBack={() => codeNavigationHistory.goBack()}
          onNavigateForward={() => codeNavigationHistory.goForward()}
          onClose={() => setCommandPaletteOpen(false)}
          onOpenFile={async (path) => {
            await openWorkspaceFile(path);
          }}
        />
      ) : null}

      {previewName ? (
        <FilePreviewDialog
          title={previewName}
          content={previewContent}
          mode={previewMode}
          botAlias={botAlias}
          previewKind={previewResult?.previewKind}
          contentType={previewResult?.contentType}
          contentBase64={previewResult?.contentBase64}
          variant="desktop"
          desktopAnchorRect={editorPaneBounds}
          loading={previewLoading}
          statusText={previewStatusText}
          readOnly={structureOnly}
          onClose={closePreview}
          onLoadFull={previewMode !== "full" && canLoadFull ? () => void loadPreview(previewName, "full") : undefined}
          onEdit={canEditPreview ? () => {
            const nextPath = previewName;
            closePreview();
            void openWorkspaceFile(nextPath);
          } : undefined}
          onDownload={() => void fileTree.downloadFile(previewName)}
          downloadProgressText={previewDownloadProgress ? formatDownloadProgress(previewDownloadProgress.downloadedBytes, previewDownloadProgress.totalBytes) : ""}
          downloadPercent={previewDownloadProgress?.percent}
        />
      ) : null}

      {definitionCandidates.length > 0 || definitionMessage ? (
        <div className="absolute inset-0 z-30 flex items-start justify-center bg-black/35 px-4 py-12">
          <motion.div
            data-testid="desktop-definition-picker"
            className="w-full max-w-2xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl"
            {...dialogPanelMotion}
          >
            <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
              <div>
                <div className="text-sm font-semibold text-[var(--text)]">代码跳转</div>
                <div className="text-xs text-[var(--muted)]">{definitionSource || "当前位置"}</div>
              </div>
              <button
                type="button"
                aria-label="关闭代码跳转"
                onClick={clearDefinitionOverlay}
                className="rounded border border-[var(--border)] px-3 py-1 text-xs text-[var(--muted)] hover:bg-[var(--surface-strong)]"
              >
                关闭
              </button>
            </div>
            {definitionMessage ? (
              <div className="px-4 py-4 text-sm text-[var(--muted)]">{definitionMessage}</div>
            ) : (
              <div className="max-h-[min(60vh,28rem)] overflow-y-auto">
                {definitionCandidates.map((item) => (
                  <button
                    key={`${item.targetType}:${item.path || item.sourceId || "unknown"}:${item.selectionRange.start.line}:${item.selectionRange.start.column}:${item.provider}`}
                    type="button"
                    onClick={() => {
                      void openDefinitionCandidate(item);
                    }}
                    className="flex w-full items-start justify-between gap-4 border-b border-[var(--border)] px-4 py-3 text-left hover:bg-[var(--surface-strong)]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-[var(--text)]">{item.path || "外部源码"}</div>
                      <div className="mt-1 text-xs text-[var(--muted)]">
                        第 {item.selectionRange.start.line} 行，列 {item.selectionRange.start.column}
                      </div>
                    </div>
                    <div className="shrink-0 text-right text-[11px] text-[var(--muted)]">
                      <div>{item.provider}</div>
                      <div>{item.targetType === "workspace" ? "工作区" : "外部源码"}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </motion.div>
        </div>
      ) : null}
    </div>
  );
}
