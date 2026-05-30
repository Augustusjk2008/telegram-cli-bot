import { clsx } from "clsx";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import type { ViewMode } from "../app/layoutMode";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileReadResult, GitTreeStatus, HostEffect, PluginOpenTarget, WorkspaceDefinitionItem } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import { GitScreen } from "../screens/GitScreen";
import { AiCapabilityGuideScreen } from "../screens/AiCapabilityGuideScreen";
import { PluginsScreen } from "../screens/PluginsScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import { AssistantOpsScreen } from "../screens/AssistantOpsScreen";
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
import { ChatPane } from "./ChatPane";
import { CommandPalette } from "./CommandPalette";
import { DebugPane } from "./DebugPane";
import { EditorPane } from "./EditorPane";
import { FileTreePane } from "./FileTreePane";
import { LanChatDock } from "./LanChatDock";
import { OutlinePane } from "./OutlinePane";
import { PaneResizer } from "./PaneResizer";
import { SearchPane } from "./SearchPane";
import { TerminalPane } from "./TerminalPane";
import { WorkbenchActivityRail } from "./WorkbenchActivityRail";
import { WorkbenchHeader } from "./WorkbenchHeader";
import { WorkbenchStatusBar } from "./WorkbenchStatusBar";
import { useDebugSession } from "./useDebugSession";
import { useEditorTabs } from "./useEditorTabs";
import { useFileTree } from "./useFileTree";
import { useWorkbenchSession } from "./useWorkbenchSession";
import { useWorkbenchState } from "./useWorkbenchState";
import { toWorkspaceRelativeSourcePath } from "./debugSourcePath";
import {
  clampPaneState,
  COLLAPSED_SIDEBAR_SIZE_PX,
  MIN_TERMINAL_HEIGHT_PX,
  PANE_RESIZER_SIZE_PX,
  type ChatWorkbenchStatus,
  type DesktopWorkspaceView,
  type FocusedWorkbenchPane,
  type TerminalOverrideState,
  type TerminalWorkbenchStatus,
  type WorkbenchActivityId,
} from "./workbenchTypes";

const RASTER_IMAGE_PREVIEW_RE = /\.(?:png|jpe?g|gif|webp)$/i;

function normalizeWorkbenchPath(value: string) {
  return String(value || "").replace(/\\/g, "/").replace(/\/+$/, "");
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
  botAvatarName?: string;
  userAvatarName?: string;
  client?: WebBotClient;
  structureOnly?: boolean;
  canWriteFiles?: boolean;
  canOpenSystemFolder?: boolean;
  chatReadOnly?: boolean;
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
  onUserAvatarChange?: (avatarName: string) => void;
  sessionCapabilities?: string[];
  canViewAssistantOps?: boolean;
  viewMode?: ViewMode;
  hasUnreadOtherBots?: boolean;
  announcementAction?: ReactNode;
  chatPaneContent?: ReactNode | ((actions: { requestPreview: (path: string) => void }) => ReactNode);
  chatStatus?: ChatWorkbenchStatus;
  onUnreadResult?: (botAlias: string) => void;
  onViewModeChange?: (viewMode: ViewMode) => void;
  onOpenBotSwitcher?: (anchorRect?: DOMRect) => void;
  onOpenBotManager?: () => void;
  onDirtyTabsChange?: (hasDirtyTabs: boolean) => void;
  onChatPaneVisibilityChange?: (visible: boolean) => void;
};

export function DesktopWorkbench({
  authToken = "",
  accountId,
  botAvatarName,
  client = new MockWebBotClient(),
  botAlias,
  userAvatarName,
  structureOnly = false,
  canWriteFiles = true,
  canOpenSystemFolder = false,
  chatReadOnly = false,
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
  onUserAvatarChange,
  sessionCapabilities = [],
  canViewAssistantOps = false,
  viewMode = "desktop",
  hasUnreadOtherBots = false,
  announcementAction,
  chatPaneContent,
  chatStatus: externalChatStatus,
  onUnreadResult,
  onViewModeChange,
  onOpenBotSwitcher,
  onOpenBotManager,
  onDirtyTabsChange,
  onChatPaneVisibilityChange,
}: Props) {
  const { paneState, toggleSidebar, toggleTerminal, toggleChat, setSidebarView, restoreSidebarView, resizePane } = useWorkbenchState();
  const fileTree = useFileTree(botAlias, client, { structureOnly });
  const tabs = useEditorTabs({ botAlias, client, structureOnly, canWriteFiles });
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
  const [workspaceView, setWorkspaceView] = useState<DesktopWorkspaceView>("editor");
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
  const [editorReveal, setEditorReveal] = useState<{ path: string; line: number } | null>(null);
  const [definitionCandidates, setDefinitionCandidates] = useState<WorkspaceDefinitionItem[]>([]);
  const [definitionMessage, setDefinitionMessage] = useState("");
  const [definitionSource, setDefinitionSource] = useState("");
  const gitDecorationRequestRef = useRef(0);
  const reduceMotion = useReducedMotion();

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
  const showAssistantOpsWorkspace = !structureOnly && canViewAssistantOps && workspaceView === "assistant-ops";
  const showGuideWorkspace = !structureOnly && workspaceView === "guide";
  const showSpecialWorkspace = showAssistantOpsWorkspace || showGuideWorkspace;
  const activeActivityItem: WorkbenchActivityId = showGuideWorkspace
    ? "guide"
    : showAssistantOpsWorkspace
      ? "assistant-ops"
      : activeSidebarView;
  const debug = useDebugSession({
    authToken,
    botAlias,
    client,
    enabled: !structureOnly && !showGuideWorkspace && layoutState.sidebarView === "debug",
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

  const showTerminalPane = !structureOnly && !showGuideWorkspace && (focusedPane === "terminal" || (!focusedPane && !layoutState.terminalCollapsed));
  const showChatPane = !showGuideWorkspace && (focusedPane === "chat" || (!focusedPane && !layoutState.chatCollapsed));
  const columnTemplate = showGuideWorkspace
    ? `${COLLAPSED_SIDEBAR_SIZE_PX}px 0px minmax(0, 1fr) 0px 0px`
    : structureOnly
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
  const centerRowTemplate = showGuideWorkspace
    ? "minmax(0, 1fr) 0px 0px"
    : structureOnly
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
  const showSidebarContent = !showGuideWorkspace && (focusedPane === "sidebar" || !layoutState.sidebarCollapsed);
  const sidebarContentMotion = resolveMotionProps(premiumMotion.sidebarContent, reduceMotion);
  const dialogPanelMotion = resolveMotionProps(premiumMotion.dialogPanel, reduceMotion);
  const availableActivityItems: WorkbenchActivityId[] = structureOnly
    ? ["files"]
    : [
        "files",
        "search",
        "outline",
        "guide",
        "debug",
        "git",
        ...(canViewAssistantOps ? ["assistant-ops" as const] : []),
        ...(canViewPlugins ? ["plugins" as const] : []),
        "settings",
      ];
  const activeEditorLine = !showSpecialWorkspace && tabs.activeTab && editorReveal?.path === tabs.activeTab.path
    ? editorReveal.line
    : tabs.activeTab
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
    setWorkspaceView("editor");
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
    setWorkspaceView("editor");
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
    if (showSpecialWorkspace && (structureOnly || (workspaceView === "assistant-ops" && !canViewAssistantOps))) {
      setWorkspaceView("editor");
    }
  }, [canViewAssistantOps, showSpecialWorkspace, structureOnly, workspaceView]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (structureOnly) {
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
        setWorkspaceView("editor");
        setSidebarView("search");
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [setSidebarView, structureOnly]);

  function toggleFocusedPane(nextPane: Exclude<FocusedWorkbenchPane, null>) {
    setFocusedPane((current) => current === nextPane ? null : nextPane);
  }

  function selectActivityItem(item: WorkbenchActivityId) {
    if (item === "assistant-ops") {
      setWorkspaceView("assistant-ops");
      setFocusedPane(null);
      return;
    }
    if (item === "guide") {
      setWorkspaceView("guide");
      setFocusedPane(null);
      return;
    }
    setWorkspaceView("editor");
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

  const revealChatPane = useCallback(() => {
    if (layoutState.chatCollapsed) {
      toggleChat();
    }
    setFocusedPane(null);
  }, [layoutState.chatCollapsed, toggleChat]);

  const resolvedChatPaneContent = typeof chatPaneContent === "function"
    ? chatPaneContent({
        requestPreview: handleRequestPreview,
      })
    : chatPaneContent;

  async function openWorkspaceFile(path: string, line?: number) {
    const target = await client.resolveFileOpenTarget(botAlias, path);
    if (!canPreviewFiles) {
      await fileTree.revealPath(path);
      setEditorReveal(null);
      return;
    }
    if (target.kind === "plugin_view") {
      await Promise.allSettled([
        tabs.openPluginView(target),
        fileTree.revealPath(path),
      ]);
      setEditorReveal(typeof line === "number" && line > 0 ? { path, line } : null);
      setWorkspaceView("editor");
      return;
    }
    if (isRasterImagePath(path) || isHtmlPreviewPath(path)) {
      await Promise.allSettled([
        loadPreview(path, "preview"),
        fileTree.revealPath(path),
      ]);
      setEditorReveal(null);
      return;
    }

    if (!canWriteFiles) {
      await Promise.allSettled([
        loadPreview(path, "preview"),
        fileTree.revealPath(path),
      ]);
      setEditorReveal(null);
      return;
    }

    await Promise.allSettled([
      tabs.openFile(path, target.pluginTargets),
      fileTree.revealPath(path),
    ]);
    setWorkspaceView("editor");
    if (line && line > 0) {
      setEditorReveal({ path, line });
      return;
    }
    setEditorReveal(null);
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
    setWorkspaceView("editor");
  }

  async function openPluginViewTab(target: PluginOpenTarget) {
    await tabs.openPluginView(target);
    setWorkspaceView("editor");
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
  }

  async function handleResolveDefinition(input: { path: string; line: number; column: number; symbol?: string }) {
    if (!allowCodeJump || structureOnly) {
      return;
    }
    try {
      const result = await client.resolveWorkspaceDefinition(botAlias, input);
      if (result.items.length === 1) {
        clearDefinitionOverlay();
        await openWorkspaceFile(result.items[0].path, result.items[0].line);
        return;
      }
      if (result.items.length > 1) {
        setDefinitionCandidates(result.items);
        setDefinitionMessage("");
        setDefinitionSource(input.symbol || `${input.path}:${input.line}:${input.column}`);
        return;
      }
      setDefinitionCandidates([]);
      setDefinitionMessage("未找到定义");
      setDefinitionSource(input.symbol || `${input.path}:${input.line}:${input.column}`);
    } catch (error) {
      setDefinitionCandidates([]);
      setDefinitionMessage(error instanceof Error ? error.message : "解析定义失败");
      setDefinitionSource(input.symbol || `${input.path}:${input.line}:${input.column}`);
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
          onOpenFile={openWorkspaceFile}
        />
      );
    }

    if (activeSidebarView === "outline") {
      return (
        <OutlinePane
          botAlias={botAlias}
          client={client}
          activeFilePath={tabs.activeTab?.path || ""}
          onOpenFile={openWorkspaceFile}
        />
      );
    }

    if (activeSidebarView === "debug") {
      return (
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
      );
    }

    if (activeSidebarView === "git") {
      return (
        <GitScreen
          botAlias={botAlias}
          botAvatarName={botAvatarName}
          client={client}
          embedded
          sessionCapabilities={sessionCapabilities}
          onOpenDiff={openGitDiffInEditor}
          onOverviewChange={(overview) => {
            setGitBranchName(overview?.repoFound ? overview.currentBranch : "");
            void refreshGitDecorations();
          }}
        />
      );
    }

    if (activeSidebarView === "plugins") {
      return (
        <PluginsScreen
          client={client}
          botAlias={botAlias}
          canOperate={botCanOperate}
          embedded
          onApplyHostEffects={runPluginHostEffects}
          onOpenPluginView={openPluginViewTab}
        />
      );
    }

    if (activeSidebarView === "settings") {
      return (
        <SettingsScreen
          botAlias={botAlias}
          botAvatarName={botAvatarName}
          client={client}
          onLogout={() => undefined}
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
          userAvatarName={userAvatarName}
          onUserAvatarChange={onUserAvatarChange}
          sessionCapabilities={sessionCapabilities}
          showBotRuntimeSettings={false}
          onOpenBotManager={onOpenBotManager}
        />
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
        sidebarVisible={!showGuideWorkspace && !layoutState.sidebarCollapsed}
        terminalVisible={!structureOnly && !showGuideWorkspace && !layoutState.terminalCollapsed}
        chatVisible={!showGuideWorkspace && !layoutState.chatCollapsed}
        availableLayoutControls={showGuideWorkspace ? [] : structureOnly ? ["sidebar", "chat"] : undefined}
        onToggleSidebar={toggleSidebar}
        onToggleTerminal={toggleTerminal}
        onToggleChat={toggleChat}
        onViewModeChange={(nextMode) => onViewModeChange?.(nextMode)}
        onOpenBotSwitcher={(anchorRect) => onOpenBotSwitcher?.(anchorRect)}
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
            {!structureOnly && showGuideWorkspace ? (
              <section
                data-testid="desktop-pane-guide"
                className="desktop-workbench-pane min-h-0 overflow-hidden"
              >
                <AiCapabilityGuideScreen embedded />
              </section>
            ) : !structureOnly ? (
              <section
                data-testid="desktop-pane-editor"
                ref={editorPaneRef}
                data-focused={focusedPane === "editor" ? "true" : "false"}
                className="desktop-workbench-pane min-h-0 overflow-hidden"
              >
                {showAssistantOpsWorkspace ? (
                  <AssistantOpsScreen
                    botAlias={botAlias}
                    client={client}
                    chatBusy={Boolean((externalChatStatus || localChatStatus).processing)}
                    onRevealChat={revealChatPane}
                  />
                ) : (
                  <EditorPane
                    botAlias={botAlias}
                    client={client}
                    tabs={tabs.tabs}
                    activeTab={tabs.activeTab}
                    activeTabPath={tabs.activeTabPath}
                    breakpointLines={tabs.activeTab ? debug.breakpointLinesForPath(tabs.activeTab.path) : []}
                    currentLine={activeEditorLine}
                    allowCodeJump={allowCodeJump}
                    onResolveDefinition={(input) => {
                      void handleResolveDefinition(input);
                    }}
                    onToggleBreakpoint={tabs.activeTab
                      ? (line) => {
                          void debug.toggleBreakpoint(tabs.activeTab?.path || "", line);
                        }
                      : undefined}
                    onActivateTab={(path) => {
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
                )}
              </section>
            ) : null}

            {!structureOnly && !showGuideWorkspace && !focusedPane && showTerminalPane ? (
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

            {!structureOnly && !showGuideWorkspace ? (
              <section
                data-testid="desktop-pane-terminal"
                data-collapsed={layoutState.terminalCollapsed ? "true" : "false"}
                data-focused={focusedPane === "terminal" ? "true" : "false"}
                className={clsx(
                  "desktop-workbench-pane min-h-0 overflow-hidden",
                  !showTerminalPane && "hidden",
                )}
              >
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
              </section>
            ) : null}
          </div>

          {!showGuideWorkspace && !focusedPane && showChatPane ? (
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

          {!showGuideWorkspace ? (
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
                  botAvatarName={botAvatarName}
                  userAvatarName={userAvatarName}
                  client={client}
                  readOnly={chatReadOnly}
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
          ) : null}
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
        rightAction={showGuideWorkspace ? null : (
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
          onClose={() => setCommandPaletteOpen(false)}
          onOpenFile={openWorkspaceFile}
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
                    key={`${item.path}:${item.line}:${item.column || 0}:${item.matchKind}`}
                    type="button"
                    onClick={() => {
                      clearDefinitionOverlay();
                      void openWorkspaceFile(item.path, item.line);
                    }}
                    className="flex w-full items-start justify-between gap-4 border-b border-[var(--border)] px-4 py-3 text-left hover:bg-[var(--surface-strong)]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-[var(--text)]">{item.path}</div>
                      <div className="mt-1 text-xs text-[var(--muted)]">
                        第 {item.line} 行
                        {item.column ? `，列 ${item.column}` : ""}
                      </div>
                    </div>
                    <div className="shrink-0 text-right text-[11px] text-[var(--muted)]">
                      <div>{item.matchKind}</div>
                      <div>{Math.round(item.confidence * 100)}%</div>
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
