import { relativeRemotePath } from "../services/remoteWorkspace";
import { useFilePreviewLoader } from "../hooks/useFilePreviewLoader";
import { clsx } from "clsx";
import { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { ViewMode } from "../app/layoutMode";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RemoteSshMenu } from "../components/RemoteSshMenu";
import { getExternalSourceErrorMessage } from "../services/types";
import type {
  CodeLocation,
  CodeNavigationIntent,
  CodeNavigationKind,
  GitTreeStatus,
  GitWorkspaceIdentity,
  HostEffect,
  LanguageServerProviderId,
  PluginOpenTarget,
  RemoteWorkspace,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import "../styles/workbench.css";
import type {
  UiThemeName,
} from "../theme";
import {
  isHtmlPreviewPath,
  getFilePreviewStatusText,
} from "../utils/filePreview";
import { getErrorMessage } from "../utils/errorMessage";
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
import { WorkbenchLayoutEditor } from "./WorkbenchLayoutEditor";
import { WorkbenchLayoutMenu } from "./WorkbenchLayoutMenu";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import { WorkbenchStatusBar } from "./WorkbenchStatusBar";
import { WorkbenchTransferStatus } from "./WorkbenchTransferStatus";
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
  resolveWorkbenchLayout,
  type ResolvedLayoutResizer,
  type WorkbenchPaneId,
} from "./workbenchLayout";
import {
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

function isSameOrDescendantWorkbenchPath(path: string, parentPath: string) {
  const normalizedPath = normalizeWorkbenchPathForCompare(path);
  const normalizedParentPath = normalizeWorkbenchPathForCompare(parentPath);
  return Boolean(
    normalizedPath
    && normalizedParentPath
    && (normalizedPath === normalizedParentPath || normalizedPath.startsWith(`${normalizedParentPath}/`)),
  );
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

type Props = {
  authToken?: string;
  accountId?: string;
  botAlias: string;
  remoteWorkspace?: RemoteWorkspace;
  gitWorkspaceIdentity?: GitWorkspaceIdentity;
  reconnectRevision?: number;
  client?: WebBotClient;
  structureOnly?: boolean;
  canWriteFiles?: boolean;
  canBrowseExternalPaths?: boolean;
  canOpenSystemFolder?: boolean;
  canUseInlineCompletion?: boolean;
  chatReadOnly?: boolean;
  chatReadOnlyReason?: string;
  chatDisabledReason?: string;
  botCanOperate?: boolean;
  canManageRemoteConnection?: boolean;
  terminalDisabledReason?: string;
  allowTrace?: boolean;
  allowCodeJump?: boolean;
  themeName?: UiThemeName;
  chatEnterToSend?: boolean;
  sessionCapabilities?: string[];
  viewMode?: ViewMode;
  hasUnreadOtherBots?: boolean;
  announcementAction?: ReactNode;
  chatPaneContent?: ReactNode | ((actions: { requestPreview: (path: string) => void }) => ReactNode);
  chatStatus?: ChatWorkbenchStatus;
  productMode?: WorkbenchProductMode;
  soloAvailable?: boolean;
  onUnreadResult?: (botAlias: string, completedAt?: string, unread?: boolean) => void;
  onProductModeChange?: (mode: WorkbenchProductMode) => void;
  onViewModeChange?: (viewMode: ViewMode) => void;
  onOpenBotSwitcher?: (anchorRect?: DOMRect) => void;
  onOpenBotManager?: () => void;
  onLogout?: () => void;
  onDirtyTabsChange?: (hasDirtyTabs: boolean) => void;
  onChatPaneVisibilityChange?: (visible: boolean) => void;
  onRemoteReconnect?: () => void;
};

export function DesktopWorkbench({
  authToken = "",
  accountId,
  client = new MockWebBotClient(),
  botAlias,
  remoteWorkspace,
  gitWorkspaceIdentity,
  reconnectRevision = 0,
  structureOnly = false,
  canWriteFiles = true,
  canBrowseExternalPaths = false,
  canOpenSystemFolder = false,
  canUseInlineCompletion = false,
  chatReadOnly = false,
  chatReadOnlyReason,
  chatDisabledReason,
  botCanOperate = true,
  canManageRemoteConnection = true,
  terminalDisabledReason = "",
  allowTrace = true,
  allowCodeJump = true,
  themeName,
  chatEnterToSend = true,
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
  onRemoteReconnect,
}: Props) {
  const {
    paneState,
    toggleSidebar,
    toggleEditor,
    toggleTerminal,
    toggleChat,
    showChat,
    setSidebarView,
    restoreSidebarView,
    resizeLayout,
    selectLayoutTemplate,
    swapLayoutPanes,
    resetLayoutTemplate,
  } = useWorkbenchState();
  const fileTree = useFileTree(botAlias, client, { structureOnly, remote: Boolean(remoteWorkspace), platform: remoteWorkspace?.platform });
  const workspaceUserScope = `${accountId || ""}\n${fileTree.rootPath}`;
  const codeNavigationScope = `${accountId || ""}\n${botAlias}\n${fileTree.rootPath}`;
  const tabs = useEditorTabs({ botAlias, client, scopeKey: workspaceUserScope, structureOnly, canWriteFiles, enableDocumentSync: !remoteWorkspace, remoteWorkspace });
  const layoutGridRef = useRef<HTMLDivElement | null>(null);
  const layoutMenuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusToLayoutMenuRef = useRef(false);
  /** Divider descriptor captured at drag start; `moved` ignores zero deltas until the pointer really moves. */
  const resizeDragRef = useRef<{ resizer: ResolvedLayoutResizer; moved: boolean } | null>(null);
  const restoringRef = useRef<{ scopeIdentity: string; requestSeq: number } | null>(null);
  const restoreRequestSerialRef = useRef(0);
  const previousBotAliasRef = useRef(botAlias);
  const previousWorkspaceRootRef = useRef("");
  // Content box of the layout grid; jsdom has no layout, so the 1440×900 fallback stays in tests.
  const [layoutBounds, setLayoutBounds] = useState({
    widthPx: 1440,
    heightPx: 900,
  });
  const [layoutEditing, setLayoutEditing] = useState(false);
  const [pendingSidebarWorkdir, setPendingSidebarWorkdir] = useState("");
  const previewRequestSeqRef = useRef(new Map<string, number>());
  const previewRequestSerialRef = useRef(0);
  const [focusedPane, setFocusedPane] = useState<FocusedWorkbenchPane>(null);
  const [isResizingPane, setIsResizingPane] = useState(false);
  const [terminalOverride, setTerminalOverride] = useState<TerminalOverrideState | null>(null);
  const [pendingTerminalOverride, setPendingTerminalOverride] = useState<TerminalOverrideState | null>(null);
  const [localChatStatus, setLocalChatStatus] = useState<ChatWorkbenchStatus>({
    state: "idle",
    processing: false,
  });
  const previewAgentId = (externalChatStatus || localChatStatus).agentId || "main";
  const chatRunning = Boolean((externalChatStatus || localChatStatus).processing || (externalChatStatus || localChatStatus).state === "running");
  const previewScopeIdentity = `${botAlias}\n${workspaceUserScope}`;
  const htmlPreviewScopeIdentity = `${previewScopeIdentity}\n${previewAgentId}\n${(externalChatStatus || localChatStatus).workingDir || ""}\n${JSON.stringify(remoteWorkspace || null)}`;
  const previewScopeIdentityRef = useRef(previewScopeIdentity);
  previewScopeIdentityRef.current = previewScopeIdentity;
  const previewLoader = useFilePreviewLoader(client, botAlias, htmlPreviewScopeIdentity);
  const previousPreviewScopeRef = useRef(htmlPreviewScopeIdentity);
  const gitWorkspaceIdentityKey = JSON.stringify(gitWorkspaceIdentity || null);
  const gitDecorationIdentityRef = useRef(gitWorkspaceIdentityKey);
  gitDecorationIdentityRef.current = gitWorkspaceIdentityKey;
  useEffect(() => {
    if (previousPreviewScopeRef.current !== htmlPreviewScopeIdentity) {
      previousPreviewScopeRef.current = htmlPreviewScopeIdentity;
      previewRequestSeqRef.current.clear();
      for (const tab of tabs.tabs) if (tab.kind === "file-preview") tabs.closeTab(tab.path);
    }
  }, [htmlPreviewScopeIdentity]);

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
  const [languageServerRestart, setLanguageServerRestart] = useState<{
    provider: LanguageServerProviderId | null;
    pending: boolean;
    error: string;
  }>({ provider: null, pending: false, error: "" });
  const gitDecorationRequestRef = useRef(0);
  const codeNavigationRequestRef = useRef(0);
  const codeNavigationAbortControllerRef = useRef<AbortController | null>(null);
  const codeNavigationScopeRef = useRef(codeNavigationScope);
  const editorRevealRequestRef = useRef(0);
  const editorNavigationCommandRef = useRef(0);
  const languageServerRestartRequestRef = useRef(0);
  const definitionSourceLocationRef = useRef<CodeNavigationHistoryLocation | null>(null);
  const definitionSourceScopeRef = useRef("");
  codeNavigationScopeRef.current = codeNavigationScope;
  const reduceMotion = useReducedMotion();
  const activeLanguageServicePath = !remoteWorkspace && (tabs.activeTab?.kind === "file" || tabs.activeTab?.kind === "external-source")
    ? tabs.activeTab.displayPath || tabs.activeTab.path
    : "";
  const languageService = useLanguageServerStatus(client, botAlias, activeLanguageServicePath, languageServerCatalogRevision);
  const canNavigateImplementation = Boolean(
    allowCodeJump
    && (tabs.activeTab?.kind === "file" || tabs.activeTab?.kind === "external-source")
    && languageService.status?.implementationSupported === true,
  );
  const refreshLanguageServerCatalogStatus = useCallback(() => {
    setLanguageServerCatalogRevision((current) => current + 1);
  }, []);
  const restartCurrentLanguageService = useCallback(async () => {
    const provider = languageService.provider;
    if (!provider || languageService.status?.status !== "available") {
      return;
    }
    const requestId = languageServerRestartRequestRef.current + 1;
    languageServerRestartRequestRef.current = requestId;
    setLanguageServerRestart({ provider, pending: true, error: "" });
    try {
      await client.restartLanguageServer(botAlias, provider);
      if (languageServerRestartRequestRef.current !== requestId) {
        return;
      }
      setLanguageServerRestart({ provider, pending: false, error: "" });
      refreshLanguageServerCatalogStatus();
    } catch (error) {
      if (languageServerRestartRequestRef.current !== requestId) {
        return;
      }
      setLanguageServerRestart({
        provider,
        pending: false,
        error: getErrorMessage(error, "重启当前语言服务失败，请稍后重试"),
      });
    }
  }, [botAlias, client, languageService.provider, languageService.status?.status, refreshLanguageServerCatalogStatus]);
  const isRestartingLanguageService = Boolean(
    languageService.provider
    && languageServerRestart.provider === languageService.provider
    && languageServerRestart.pending,
  ) || languageService.status?.runtimeState === "restarting";
  const languageServerRestartError = languageServerRestart.provider === languageService.provider
    ? languageServerRestart.error
    : "";
  const canRestartLanguageService = Boolean(
    languageService.provider
    && languageService.status?.status === "available",
  );

  useEffect(() => {
    clearDefinitionOverlay();
    return () => {
      codeNavigationRequestRef.current += 1;
      codeNavigationAbortControllerRef.current?.abort();
      codeNavigationAbortControllerRef.current = null;
    };
  }, [client, codeNavigationScope]);

  const codeNavigationHistory = useCodeNavigationHistory({
    scopeKey: codeNavigationScope,
    onNavigate: async (location) => {
      const scope = codeNavigationScopeRef.current;
      if (location.sourceId) {
        const opened = await tabs.openExternalSource({
          sourceId: location.sourceId,
          displayPath: location.displayPath,
        });
        if (opened && codeNavigationScopeRef.current === scope) {
          setEditorReveal({
            path: location.path || `external-source:${location.sourceId}`,
            line: location.line,
            column: location.column,
            requestId: `external-history-${Date.now()}`,
          });
        }
        return opened;
      }
      return openWorkspaceFile(
        location.path,
        location.line,
        location.column,
        "",
        () => codeNavigationScopeRef.current === scope,
      );
    },
  });

  const layoutState = paneState;
  const canViewPlugins = sessionCapabilities.includes("view_plugins");
  const canPreviewFiles = !structureOnly;
  const canMutateFiles = canPreviewFiles && canWriteFiles;
  const canUseRemoteGit = sessionCapabilities.length === 0 || sessionCapabilities.includes("git_ops");
  const remoteActivityItems: WorkbenchActivityId[] = [
    "files",
    ...(canUseRemoteGit ? ["git" as const] : []),
    "settings",
  ];
  const remoteSidebarUnavailable = Boolean(remoteWorkspace)
    && !remoteActivityItems.includes(layoutState.sidebarView);
  const activeSidebarView = remoteSidebarUnavailable || (!canViewPlugins && layoutState.sidebarView === "plugins")
    ? "files"
    : layoutState.sidebarView;
  const activeActivityItem: WorkbenchActivityId = activeSidebarView;
  const debug = useDebugSession({
    authToken,
    botAlias,
    client,
    enabled: !remoteWorkspace && !structureOnly && layoutState.sidebarView === "debug",
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
          activeTabPath: tabs.activeTab?.kind === "external-source" || tabs.activeTab?.kind === "file-preview"
            ? ""
            : tabs.activeTabPath,
          terminalOverrideCwd: terminalOverride?.cwd,
          focusedPane,
          tabs: tabs.buildPersistenceSnapshot(),
        }
      : null,
  });

  const paneAvailability = useMemo<Record<WorkbenchPaneId, boolean>>(() => ({
    sidebar: true,
    editor: !structureOnly,
    terminal: !structureOnly,
    chat: true,
  }), [structureOnly]);
  const paneCollapsed = useMemo<Record<WorkbenchPaneId, boolean>>(() => ({
    sidebar: layoutState.sidebarCollapsed,
    editor: layoutState.editorCollapsed,
    terminal: layoutState.terminalCollapsed,
    chat: layoutState.chatCollapsed,
  }), [layoutState.chatCollapsed, layoutState.editorCollapsed, layoutState.sidebarCollapsed, layoutState.terminalCollapsed]);
  // Layout changes only edit grid templates and placements; the pane sections never move in the DOM.
  const resolvedLayout = useMemo(() => resolveWorkbenchLayout({
    layout: layoutState.layout,
    available: paneAvailability,
    collapsed: paneCollapsed,
    focusedPane,
    editing: layoutEditing,
    container: { width: layoutBounds.widthPx, height: layoutBounds.heightPx },
  }), [focusedPane, layoutBounds, layoutEditing, layoutState.layout, paneAvailability, paneCollapsed]);
  const sidebarPlacement = resolvedLayout.panes.sidebar;
  const editorPlacement = resolvedLayout.panes.editor;
  const terminalPlacement = resolvedLayout.panes.terminal;
  const chatPlacement = resolvedLayout.panes.chat;
  const showEditorPane = editorPlacement.displayed;
  useEffect(() => {
    previewLoader.reconcile(tabs.tabs.filter((tab) => tab.kind === "file-preview").map((tab) => tab.sourcePath || ""), showEditorPane && tabs.activeTab?.kind === "file-preview" ? tabs.activeTab.sourcePath || "" : "");
  }, [previewLoader, tabs.tabs, tabs.activeTab, showEditorPane]);
  const showTerminalPane = terminalPlacement.displayed;
  const showChatPane = chatPlacement.displayed;
  const workspaceName = fileTree.rootPath.split(/[\\/]+/).filter(Boolean).pop() || fileTree.rootPath || "/";
  const showSidebarContent = focusedPane === "sidebar" || !layoutState.sidebarCollapsed;
  const sidebarRailAtEnd = sidebarPlacement.railSide === "end";
  const sidebarContentMotion = resolveMotionProps(premiumMotion.sidebarContent, reduceMotion);
  const dialogPanelMotion = resolveMotionProps(premiumMotion.dialogPanel, reduceMotion);
  const availableActivityItems: WorkbenchActivityId[] = structureOnly
    ? ["files"]
    : remoteWorkspace
      ? remoteActivityItems
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
    const requestIdentity = gitWorkspaceIdentityKey;
    try {
      const next = await client.getGitTreeStatus(botAlias);
      if (gitDecorationRequestRef.current !== requestId || gitDecorationIdentityRef.current !== requestIdentity) {
        return;
      }
      setGitDecorations(next.repoFound ? next.items : {});
      setGitRepoPath(next.repoFound ? next.repoPath || "" : "");
    } catch {
      if (gitDecorationRequestRef.current !== requestId || gitDecorationIdentityRef.current !== requestIdentity) {
        return;
      }
      setGitDecorations({});
      setGitRepoPath("");
    }
  }, [botAlias, client, gitWorkspaceIdentityKey, reconnectRevision, remoteWorkspace]);

  const refreshWorkspaceChrome = useCallback(async (options?: { preserveExpandedPaths?: boolean; rootPath?: string; gitDelayMs?: number }) => {
    const nextRootPath = await fileTree.refreshTreeAndRoot({
      preserveExpandedPaths: options?.preserveExpandedPaths,
      rootPath: options?.rootPath,
    });
    await refreshGitDecorations();
    return nextRootPath;
  }, [fileTree, refreshGitDecorations, remoteWorkspace]);

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
    // The layout menu trigger is disabled while rearranging, so focus can only return after this render.
    if (!layoutEditing && returnFocusToLayoutMenuRef.current) {
      returnFocusToLayoutMenuRef.current = false;
      layoutMenuTriggerRef.current?.focus();
    }
  }, [layoutEditing]);

  useLayoutEffect(() => {
    const updateLayoutBounds = () => {
      const grid = layoutGridRef.current;
      const gridStyle = grid ? window.getComputedStyle(grid) : null;
      // Client dimensions exclude borders; grid tracks also exclude the container padding.
      const nextWidthPx = grid
        ? grid.clientWidth - (parseFloat(gridStyle?.paddingLeft || "0") || 0) - (parseFloat(gridStyle?.paddingRight || "0") || 0)
        : 0;
      const nextHeightPx = grid
        ? grid.clientHeight - (parseFloat(gridStyle?.paddingTop || "0") || 0) - (parseFloat(gridStyle?.paddingBottom || "0") || 0)
        : 0;

      setLayoutBounds((current) => {
        const widthPx = nextWidthPx > 0 ? nextWidthPx : current.widthPx;
        const heightPx = nextHeightPx > 0 ? nextHeightPx : current.heightPx;
        return widthPx === current.widthPx && heightPx === current.heightPx
          ? current
          : { widthPx, heightPx };
      });
    };

    updateLayoutBounds();
    const observer = window.ResizeObserver ? new window.ResizeObserver(updateLayoutBounds) : null;
    if (layoutGridRef.current) observer?.observe(layoutGridRef.current);
    window.addEventListener("resize", updateLayoutBounds);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateLayoutBounds);
    };
  }, [focusedPane, themeName]);

  useEffect(() => {
    if (previousBotAliasRef.current === botAlias) {
      return;
    }
    previousBotAliasRef.current = botAlias;
    restoreSidebarView("files");
    setFocusedPane(null);
    setLayoutEditing(false);
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
    setLayoutEditing(false);
    setTerminalOverride(null);
    setPendingTerminalOverride(null);
    setPendingSidebarWorkdir("");
    void tabs.restoreFromSnapshot([], "");
  }, [fileTree.rootPath, restoreSidebarView, tabs]);

  useEffect(() => {
    if (
      !fileTree.rootPath
      || !session.restoreLoaded
      || session.restoreApplied
      || restoringRef.current?.scopeIdentity === previewScopeIdentity
    ) {
      return;
    }

    const restoreRequest = {
      scopeIdentity: previewScopeIdentity,
      requestSeq: restoreRequestSerialRef.current + 1,
    };
    restoreRequestSerialRef.current = restoreRequest.requestSeq;
    restoringRef.current = restoreRequest;
    let cancelled = false;
    const isCurrentRestore = () => (
      !cancelled
      && restoringRef.current === restoreRequest
      && previewScopeIdentityRef.current === restoreRequest.scopeIdentity
    );

    void (async () => {
      try {
        const restoredSession = session.restoredSession;
        if (restoredSession) {
          restoreSidebarView(remoteWorkspace && restoredSession.sidebarView !== "git" ? "files" : restoredSession.sidebarView);
          setFocusedPane(restoredSession.focusedPane ?? null);
          setTerminalOverride(restoredSession.terminalOverrideCwd
            ? { cwd: restoredSession.terminalOverrideCwd, source: "manual" }
            : null);
          await fileTree.restoreExpandedPaths(restoredSession.expandedPaths);
          if (!isCurrentRestore()) {
            return;
          }
          if (restoredSession.selectedTreePath) {
            fileTree.selectPath(restoredSession.selectedTreePath);
          }
          await tabs.restoreFromSnapshot(restoredSession.tabs, restoredSession.activeTabPath);
        }
      } finally {
        const shouldMarkApplied = isCurrentRestore();
        if (restoringRef.current === restoreRequest) {
          restoringRef.current = null;
        }
        if (shouldMarkApplied) {
          session.markRestoreApplied();
        }
      }
    })();

    return () => {
      cancelled = true;
      if (restoringRef.current === restoreRequest) {
        restoringRef.current = null;
      }
    };
  }, [fileTree.rootPath, previewScopeIdentity, session.restoreApplied, session.restoreLoaded, session.restoredSession]);

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
  }, [botAlias, client, fileTree.rootPath, remoteWorkspace]);

  useEffect(() => {
    if (!fileTree.rootPath) {
      return;
    }
    void refreshGitDecorations();
  }, [fileTree.rootPath, refreshGitDecorations, remoteWorkspace]);

  useEffect(() => {
    if (!terminalStatus.currentCwd && fileTree.rootPath) {
      setTerminalStatus((current) => ({
        ...current,
        currentCwd: fileTree.rootPath,
      }));
    }
  }, [fileTree.rootPath, terminalStatus.currentCwd]);

  useEffect(() => {
    if ((structureOnly && layoutState.sidebarView !== "files") || remoteSidebarUnavailable) {
      setSidebarView("files");
    }
  }, [layoutState.sidebarView, setSidebarView, structureOnly, remoteSidebarUnavailable]);


  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (structureOnly || remoteWorkspace) {
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
  }, [codeNavigationHistory.handleShortcut, setSidebarView, structureOnly, remoteWorkspace]);

  function toggleFocusedPane(nextPane: Exclude<FocusedWorkbenchPane, null>) {
    setFocusedPane((current) => current === nextPane ? null : nextPane);
  }

  function startLayoutEditing() {
    setFocusedPane(null);
    setLayoutEditing(true);
  }

  function finishLayoutEditing() {
    returnFocusToLayoutMenuRef.current = true;
    setLayoutEditing(false);
  }

  function handleRemoteConnected() {
    if (!remoteWorkspace) return;
    onRemoteReconnect?.();
    void refreshWorkspaceChrome({ preserveExpandedPaths: true, rootPath: remoteWorkspace.root });
  }

  function selectActivityItem(item: WorkbenchActivityId) {
    if (remoteWorkspace && !remoteActivityItems.includes(item)) return;
    setSidebarView(item);
  }

  function isRasterImagePath(path: string) {
    return RASTER_IMAGE_PREVIEW_RE.test(path);
  }

  function cancelPreviewRequestsUnder(path: string) {
    for (const requestPath of previewRequestSeqRef.current.keys()) {
      if (isSameOrDescendantWorkbenchPath(requestPath, path)) {
        previewRequestSeqRef.current.delete(requestPath);
        previewLoader.cancel(requestPath);
      }
    }
  }

  async function loadPreview(
    path: string,
    mode: "preview" | "full",
    options?: { activate?: boolean },
  ) {
    if (!canPreviewFiles) {
      return;
    }
    path = remoteWorkspace ? relativeRemotePath(path, remoteWorkspace.root, remoteWorkspace.platform) : path.trim();
    const requestScopeIdentity = previewScopeIdentityRef.current;
    const requestSeq = previewRequestSerialRef.current + 1;
    previewRequestSerialRef.current = requestSeq;
    previewRequestSeqRef.current.set(path, requestSeq);
    tabs.openFilePreview({
      path,
      htmlPreview: null,
      loading: true,
      statusText: mode === "full" ? "正在读取全文" : "正在加载预览",
      activate: options?.activate,
    });
    try {
      const data = await previewLoader.load(path, { mode, remote: remoteWorkspace ? true : undefined, agentId: previewAgentId });
      if (!data || previewScopeIdentityRef.current !== requestScopeIdentity || previewRequestSeqRef.current.get(path) !== requestSeq) {
        data?.htmlPreview?.dispose();
        return;
      }
      const { result, htmlPreview } = data;
      tabs.openFilePreview({
        path,
        result,
        htmlPreview,
        loading: false,
        statusText: getFilePreviewStatusText(result),
        activate: false,
      });
    } catch (error) {
      if (
        previewScopeIdentityRef.current !== requestScopeIdentity
        || previewRequestSeqRef.current.get(path) !== requestSeq
      ) {
        return;
      }
      tabs.openFilePreview({
        path,
        loading: false,
        statusText: "",
        error: getErrorMessage(error, mode === "full" ? "读取全文失败" : "预览文件失败"),
        activate: false,
      });
    } finally {
      if (previewRequestSeqRef.current.get(path) === requestSeq) {
        previewRequestSeqRef.current.delete(path);
      }
    }
  }

  const handleRequestPreview = (path: string) => {
    void loadPreview(path, "preview");
  };

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
    expectedScopeIdentity = previewScopeIdentityRef.current,
  ) {
    const isCurrentRequest = () => (
      isCurrent()
      && previewScopeIdentityRef.current === expectedScopeIdentity
    );
    if (!isCurrentRequest()) {
      return false;
    }
    const target = remoteWorkspace ? { kind: "file" as const } : await client.resolveFileOpenTarget(botAlias, path);
    if (!isCurrentRequest()) {
      return false;
    }
    if (!canPreviewFiles) {
      await fileTree.revealPath(path);
      if (!isCurrentRequest()) return false;
      setEditorReveal(null);
      return false;
    }
    if (target.kind === "plugin_view") {
      await Promise.allSettled([
        tabs.openPluginView(target),
        fileTree.revealPath(path),
      ]);
      if (!isCurrentRequest()) return false;
      setEditorReveal(null);
      return false;
    }
    if (isRasterImagePath(path) || isHtmlPreviewPath(path)) {
      await Promise.allSettled([
        loadPreview(path, "preview"),
        fileTree.revealPath(path),
      ]);
      if (!isCurrentRequest()) return false;
      setEditorReveal(null);
      return false;
    }

    if (!canWriteFiles) {
      await Promise.allSettled([
        loadPreview(path, "preview"),
        fileTree.revealPath(path),
      ]);
      if (!isCurrentRequest()) return false;
      setEditorReveal(null);
      return false;
    }

    await Promise.allSettled([
      tabs.openFile(path, target.pluginTargets),
      fileTree.revealPath(path),
    ]);
    if (!isCurrentRequest()) {
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

  async function openPluginViewTab(
    target: PluginOpenTarget,
    expectedScopeIdentity = previewScopeIdentityRef.current,
  ) {
    if (previewScopeIdentityRef.current !== expectedScopeIdentity) {
      return;
    }
    await tabs.openPluginView(target);
    if (previewScopeIdentityRef.current !== expectedScopeIdentity) {
      return;
    }
    const sourcePath = typeof target.input.path === "string" ? target.input.path : "";
    if (sourcePath) {
      setSidebarView("files");
      await fileTree.revealPath(sourcePath);
    }
  }

  async function runPluginHostEffects(effects: HostEffect[], sourcePluginId = "") {
    const effectScopeIdentity = previewScopeIdentityRef.current;
    for (const effect of effects) {
      if (previewScopeIdentityRef.current !== effectScopeIdentity) {
        return;
      }
      if (effect.type === "open_file") {
        setSidebarView("files");
        await openWorkspaceFile(effect.path, effect.line, effect.column ?? 1, "", () => true, effectScopeIdentity);
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
      if (effect.type === "install_plugin_runtime") {
        if (Object.keys(effect).some((key) => key !== "type")) {
          throw new Error("运行时安装不接受插件提供的运行时参数");
        }
        if (!sourcePluginId) {
          throw new Error("运行时安装缺少插件来源");
        }
        await client.installPluginRuntime(botAlias, sourcePluginId);
        continue;
      }
      await openPluginViewTab(effect, effectScopeIdentity);
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
      || (tabs.activeTab?.kind !== "file" && tabs.activeTab?.kind !== "external-source")
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
      path: item.targetType === "external" && item.sourceId
        ? `external-source:${item.sourceId}`
        : path,
      line: item.selectionRange.start.line,
      column: item.selectionRange.start.column,
      ...(item.targetType === "external" && item.sourceId ? {
        sourceId: item.sourceId,
        displayPath: item.displayPath || path || "外部源码",
      } : {}),
    };
    clearDefinitionOverlay();
    if (!scope || codeNavigationScopeRef.current !== scope) {
      return;
    }
    if (item.targetType === "external") {
      if (!item.sourceId) {
        setDefinitionMessage("不支持的外部源码类型，仅支持 file:// 源码");
        setDefinitionSource(path || "外部源码");
        return;
      }
      const opened = await tabs.openExternalSource({
        sourceId: item.sourceId,
        displayPath: item.displayPath || path || "外部源码",
      });
      if (opened && source && codeNavigationScopeRef.current === scope) {
        codeNavigationHistory.recordNavigation(source, target);
        setEditorReveal({
          path: target.path,
          line: target.line,
          column: target.column,
          requestId: `external-reveal-${Date.now()}`,
        });
      }
      return;
    }
    if (!path) {
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
    if (
      !activeTab
      || (activeTab.kind !== "file" && activeTab.kind !== "external-source")
      || activeTab.path !== input.path
    ) {
      return;
    }
    const source = {
      path: input.path,
      line: input.line,
      column: input.column,
      ...(activeTab.kind === "external-source" && activeTab.sourceId ? {
        sourceId: activeTab.sourceId,
        displayPath: activeTab.displayPath || activeTab.basename,
      } : {}),
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
          ...(activeTab.kind === "external-source" && activeTab.sourceId
            ? { sourceId: activeTab.sourceId }
            : { path: activeTab.path }),
          languageId: inferFileEditorLanguageId(activeTab.displayPath || activeTab.path),
          version: Math.max(1, Math.trunc(activeTab.documentVersion || 1)),
          content: activeTab.content,
        },
        position: { line: input.line, column: input.column },
      }, controller?.signal);
      if (!isCurrent()) {
        return;
      }
      const semanticItems = result.items.filter((item) => (
        (item.targetType === "workspace" && Boolean(item.path))
        || (item.targetType === "external" && Boolean(item.sourceId))
      ));
      const rejectedExternalItem = result.items.find((item) => item.targetType === "external" && !item.sourceId);
      if (semanticItems.length === 0 && rejectedExternalItem) {
        setDefinitionCandidates([]);
        setDefinitionMessage(getExternalSourceErrorMessage({
          code: result.message ? undefined : "unsupported_external_source_uri",
          message: result.message || "不支持的外部源码类型",
        }));
        setDefinitionSource(input.symbol || `${input.path}:${input.line}:${input.column}`);
        definitionSourceLocationRef.current = null;
        return;
      }
      if (semanticItems.length === 1) {
        clearDefinitionOverlay();
        const item = semanticItems[0];
        const target = {
          path: item.targetType === "external" && item.sourceId
            ? `external-source:${item.sourceId}`
            : item.path || "",
          line: item.selectionRange.start.line,
          column: item.selectionRange.start.column,
          ...(item.targetType === "external" && item.sourceId ? {
            sourceId: item.sourceId,
            displayPath: item.displayPath || item.path || "外部源码",
          } : {}),
        };
        const opened = item.targetType === "external" && item.sourceId
          ? await tabs.openExternalSource({ sourceId: item.sourceId, displayPath: item.displayPath || item.path || "外部源码" })
          : await openWorkspaceFile(
              target.path,
              target.line,
              target.column,
              result.requestId || requestId,
              isCurrent,
            );
        if (opened && isCurrent()) {
          codeNavigationHistory.recordNavigation(source, target);
          if (item.targetType === "external") {
            setEditorReveal({
              path: target.path,
              line: target.line,
              column: target.column,
              requestId: result.requestId || requestId,
            });
          }
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
      setDefinitionMessage(getExternalSourceErrorMessage({
        message: result.message || (input.kind === "implementation" ? "未找到语义实现" : "未找到语义定义"),
      }));
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
      setDefinitionMessage(getExternalSourceErrorMessage(error));
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
    if (await fileTree.uploadFiles(files)) {
      await refreshWorkspaceChrome({ preserveExpandedPaths: true });
    }
  }

  async function handleFileTreeHome() {
    const workingDir = remoteWorkspace?.root || await client.getCurrentPath(botAlias);
    if (!structureOnly && !remoteWorkspace) {
      await client.changeDirectory(botAlias, workingDir);
    }
    await refreshWorkspaceChrome({ rootPath: workingDir });
  }

  async function handleNavigateExternalPath(path: string) {
    if (!structureOnly) {
      await client.changeDirectory(botAlias, path);
    }
    await refreshWorkspaceChrome({ rootPath: path });
  }

  async function handleOpenSystemFolder() {
    await client.openBotWorkdir(botAlias);
  }

  function renderSidebarContent() {
    if (structureOnly || activeSidebarView === "files") {
      return (
        <FileTreePane
          tree={fileTree}
          themeName={themeName}
          onOpenFile={(path) => {
            void openWorkspaceFile(path);
          }}
          onCreatedFile={(path, content, lastModifiedNs) => {
            tabs.openCreatedFile(path, content, lastModifiedNs);
            fileTree.highlightPath(path);
          }}
          onRenamedFile={(oldPath, nextPath) => {
            cancelPreviewRequestsUnder(oldPath);
            const renamedTabs = tabs.syncRenamedPath(oldPath, nextPath);
            renamedTabs.previews.forEach((preview) => {
              if (preview.loading && preview.path) {
                void loadPreview(preview.path, preview.full ? "full" : "preview", { activate: false });
              }
            });
            renamedTabs.pluginTargets.forEach((target) => {
              void tabs.openPluginView(target, { activate: false });
            });
            fileTree.highlightPath(nextPath);
          }}
          onDeletedFile={(path) => {
            cancelPreviewRequestsUnder(path);
            tabs.closeDeletedPath(path);
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
          onRequestNavigatePath={handleNavigateExternalPath}
          onRequestOpenSystemFolder={canOpenSystemFolder ? handleOpenSystemFolder : undefined}
          gitDecorations={gitDecorations}
          onRefreshGitDecorations={refreshGitDecorations}
          onRequestSetWorkdir={(path) => {
            setPendingSidebarWorkdir(path);
            setSidebarView("settings");
          }}
          remote={Boolean(remoteWorkspace)}
          remotePlatform={remoteWorkspace?.platform}
          structureOnly={structureOnly}
          canWriteFiles={canWriteFiles}
          canBrowseExternalPaths={canBrowseExternalPaths}
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
          remote={Boolean(remoteWorkspace)}
          workspaceIdentity={gitWorkspaceIdentity}
          reconnectRevision={reconnectRevision}
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
          embedded
          prefilledWorkdir={remoteWorkspace ? undefined : pendingSidebarWorkdir || fileTree.rootPath}
          onWorkdirUpdated={(nextWorkdir) => {
            setPendingSidebarWorkdir(nextWorkdir);
            void refreshWorkspaceChrome({ preserveExpandedPaths: true, rootPath: nextWorkdir });
          }}
          onRemoteConnected={remoteWorkspace ? handleRemoteConnected : undefined}
          onCliSwitched={showChat}
          sessionCapabilities={sessionCapabilities}
        />
        </Suspense>
      );
    }
  }

  const lanChatDock = !remoteWorkspace && (
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
      className="desktop-workbench-root orbit-shell theme-illustration-host grid h-[100dvh] min-h-0 w-full grid-cols-[minmax(0,1fr)]"
      style={{ gridTemplateRows: "auto minmax(0,1fr) auto" }}
    >
      <div data-testid="desktop-workbench-canvas" className="orbit-canvas" aria-hidden="true">
        <ThemeIllustrationLayer surface="workbench" className="workbench-canvas-illustration" />
      </div>
      {focusedPane ? (
        <button
          type="button"
          data-testid="workbench-focus-backdrop"
          aria-label="退出聚焦模式"
          onClick={() => setFocusedPane(null)}
          className="absolute inset-0 z-20 bg-transparent"
        />
      ) : null}

      <WorkbenchHeader
        currentBot={botAlias}
        workspaceName={workspaceName}
        branchName={gitBranchName}
        viewMode={viewMode}
        hasUnreadOtherBots={hasUnreadOtherBots}
        announcementAction={announcementAction}
        workspaceAction={remoteWorkspace ? <RemoteSshMenu client={client} botAlias={botAlias} remote={remoteWorkspace} disabled={!botCanOperate || !canManageRemoteConnection} onConnected={handleRemoteConnected} /> : undefined}
        sidebarVisible={!layoutState.sidebarCollapsed}
        editorVisible={!structureOnly && !layoutState.editorCollapsed}
        terminalVisible={!structureOnly && !layoutState.terminalCollapsed}
        chatVisible={!layoutState.chatCollapsed}
        availableLayoutControls={structureOnly ? ["sidebar", "chat"] : undefined}
        layoutAction={(
          <WorkbenchLayoutMenu
            activeTemplate={layoutState.layout.activeTemplate}
            layout={layoutState.layout}
            disabled={layoutEditing}
            triggerRef={layoutMenuTriggerRef}
            onSelectTemplate={selectLayoutTemplate}
            onStartRearrange={startLayoutEditing}
            onResetTemplate={resetLayoutTemplate}
          />
        )}
        productMode={productMode}
        soloAvailable={soloAvailable}
        onProductModeChange={onProductModeChange}
        onToggleSidebar={toggleSidebar}
        onToggleEditor={toggleEditor}
        onToggleTerminal={toggleTerminal}
        onToggleChat={toggleChat}
        onViewModeChange={(nextMode) => onViewModeChange?.(nextMode)}
        onOpenBotSwitcher={(anchorRect) => onOpenBotSwitcher?.(anchorRect)}
        onOpenCommandPalette={!structureOnly && !remoteWorkspace ? () => setCommandPaletteOpen(true) : undefined}
        onLogout={() => onLogout?.()}
      />

      <div data-testid="desktop-workbench-shell" className="desktop-workbench-shell relative min-h-0 overflow-hidden">
        {/* Children stay flat and in this fixed order; layout changes only edit grid templates and placements. */}
        <div
          data-testid="desktop-workbench-columns"
          data-layout-template={resolvedLayout.templateId}
          data-layout-editing={layoutEditing ? "true" : "false"}
          ref={layoutGridRef}
          className="grid h-full min-h-0"
          style={{ gridTemplateColumns: resolvedLayout.gridTemplateColumns, gridTemplateRows: resolvedLayout.gridTemplateRows }}
        >
          <section
            key="pane-sidebar"
            data-testid="desktop-pane-files"
            data-layout-slot={sidebarPlacement.slot}
            data-collapsed={layoutState.sidebarCollapsed ? "true" : "false"}
            data-focused={focusedPane === "sidebar" ? "true" : "false"}
            inert={layoutEditing || undefined}
            className={clsx(
              "desktop-workbench-pane orbit-island grid min-h-0 overflow-hidden",
              // Never `hidden`: a sidebar without space stays in its 0-size track so the tree keeps its scroll position.
              !sidebarPlacement.displayed && "invisible",
            )}
            style={{ gridColumn: sidebarPlacement.gridColumn, gridRow: sidebarPlacement.gridRow }}
          >
            <div
              className={clsx(
                "theme-illustration-content grid min-h-0",
                !showSidebarContent
                  ? "grid-cols-[48px]"
                  : sidebarRailAtEnd
                    ? "grid-cols-[minmax(0,1fr)_48px]"
                    : "grid-cols-[48px_minmax(0,1fr)]",
              )}
            >
              <div
                data-testid="desktop-workbench-activity-rail-illustration-host"
                className={clsx(
                  "workbench-activity-rail-illustration-host relative min-h-0 min-w-0 overflow-hidden",
                  showSidebarContent && sidebarRailAtEnd && "col-start-2 row-start-1",
                )}
              >
                <WorkbenchActivityRail
                  activeItem={activeActivityItem}
                  sidebarCollapsed={layoutState.sidebarCollapsed}
                  availableItems={availableActivityItems}
                  side={sidebarPlacement.railSide}
                  onToggleSidebar={toggleSidebar}
                  onSelectItem={selectActivityItem}
                />
              </div>

              {showSidebarContent ? (
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div
                    key={activeSidebarView}
                    className={clsx(
                      "flex min-h-0 min-w-0 flex-1 flex-col",
                      sidebarRailAtEnd && "col-start-1 row-start-1",
                    )}
                    {...sidebarContentMotion}
                  >
                    {activeSidebarView === "files" ? (
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

          {!structureOnly ? (
            <section
              key="pane-editor"
              data-testid="desktop-pane-editor"
              data-layout-slot={editorPlacement.slot}
              data-collapsed={layoutState.editorCollapsed ? "true" : "false"}
              data-focused={focusedPane === "editor" ? "true" : "false"}
              inert={layoutEditing || undefined}
              className={clsx(
                "desktop-workbench-pane orbit-island orbit-island--solid min-h-0 overflow-hidden",
                !showEditorPane && "hidden",
              )}
              style={{ gridColumn: editorPlacement.gridColumn, gridRow: editorPlacement.gridRow }}
            >
              <div className="theme-illustration-content h-full min-h-0">
                <Suspense fallback={paneFallback}>
                  <EditorPane
                  previewVisible={showEditorPane}
                  remotePlatform={remoteWorkspace ? remoteWorkspace.platform || "posix" : undefined}
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
                  onToggleBreakpoint={!remoteWorkspace && tabs.activeTab
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
                  onCloseAll={tabs.closeAllTabs}
                  onCloseOthers={tabs.closeOtherTabs}
                  onCloseTabsToRight={tabs.closeTabsToRight}
                  onReopenLastClosed={() => {
                    void tabs.reopenLastClosedTab();
                  }}
                  onRevealInTree={(path) => {
                    setSidebarView("files");
                    void fileTree.revealPath(path);
                  }}
                  onSwitchFileView={(path, view) => {
                    if (view === "preview") {
                      void loadPreview(path, "preview");
                      return;
                    }
                    void tabs.openFile(path);
                  }}
                  onApplyHostEffects={runPluginHostEffects}
                  onClosePluginTab={(path) => {
                    tabs.closePath(path);
                  }}
                  onReopenPluginView={(target) => {
                    void openPluginViewTab(target);
                  }}
                  onLoadFullPreview={(path) => void loadPreview(path, "full")}
                  focused={focusedPane === "editor"}
                  onToggleFocus={() => toggleFocusedPane("editor")}
                  />
                </Suspense>
              </div>
            </section>
          ) : null}

          {!structureOnly ? (
            <section
              key="pane-terminal"
              data-testid="desktop-pane-terminal"
              data-layout-slot={terminalPlacement.slot}
              data-collapsed={layoutState.terminalCollapsed ? "true" : "false"}
              data-focused={focusedPane === "terminal" ? "true" : "false"}
              inert={layoutEditing || undefined}
              className={clsx(
                "desktop-workbench-pane orbit-island orbit-island--solid min-h-0 overflow-hidden",
                !showTerminalPane && "hidden",
              )}
              style={{ gridColumn: terminalPlacement.gridColumn, gridRow: terminalPlacement.gridRow }}
            >
              <div className="theme-illustration-content h-full min-h-0">
                <Suspense fallback={paneFallback}>
                  <TerminalPane
                    authToken={authToken}
                    botAlias={botAlias}
                    client={client}
                    preferredWorkingDir={terminalOverride?.cwd || fileTree.rootPath}
                    pendingWorkingDir={pendingTerminalOverride?.cwd}
                    themeName={themeName}
                    disabledReason={terminalDisabledReason}
                    remote={Boolean(remoteWorkspace)}
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
              </div>
            </section>
          ) : null}

          <section
            key="pane-chat"
            data-testid="desktop-pane-chat"
            data-layout-slot={chatPlacement.slot}
            data-collapsed={layoutState.chatCollapsed ? "true" : "false"}
            data-focused={focusedPane === "chat" ? "true" : "false"}
            data-running={chatRunning ? "true" : "false"}
            inert={layoutEditing || undefined}
            className={clsx(
              "desktop-workbench-pane orbit-island orbit-island--reading min-h-0 overflow-hidden",
              !showChatPane && "hidden",
            )}
            style={{ gridColumn: chatPlacement.gridColumn, gridRow: chatPlacement.gridRow }}
          >
            {chatRunning ? <div className="orbit-sweep chat-pane-sweep" aria-hidden="true" /> : null}
            <div className="theme-illustration-content h-full min-h-0">
              {resolvedChatPaneContent || (
                <ChatPane
                  botAlias={botAlias}
                  client={client}
                  readOnly={chatReadOnly}
                  readOnlyReason={chatReadOnlyReason}
                  disabledReason={chatDisabledReason}
                  allowTrace={allowTrace}
                  enterToSend={chatEnterToSend}
                  visible={showChatPane}
                  focused={focusedPane === "chat"}
                  onToggleFocus={() => toggleFocusedPane("chat")}
                  onUnreadResult={onUnreadResult}
                  onWorkbenchStatusChange={setLocalChatStatus}
                  onRequestDesktopPreview={handleRequestPreview}
                />
              )}
            </div>
          </section>

          {resolvedLayout.resizers.map((resizer) => (
            <PaneResizer
              key={resizer.id}
              ariaLabel={resizer.ariaLabel}
              axis={resizer.axis}
              style={{ gridColumn: resizer.gridColumn, gridRow: resizer.gridRow }}
              onResizeStart={() => {
                resizeDragRef.current = { resizer, moved: false };
                setIsResizingPane(true);
              }}
              onResizeDelta={(deltaPx) => {
                const drag = resizeDragRef.current;
                if (!drag || (!drag.moved && deltaPx === 0)) {
                  return;
                }
                drag.moved = true;
                resizeLayout(drag.resizer, deltaPx);
              }}
              onResizeEnd={() => {
                resizeDragRef.current = null;
                setIsResizingPane(false);
              }}
            />
          ))}

          {layoutEditing ? (
            <WorkbenchLayoutEditor
              resolved={resolvedLayout}
              available={paneAvailability}
              collapsed={paneCollapsed}
              onSwap={swapLayoutPanes}
              onReset={resetLayoutTemplate}
              onDone={finishLayoutEditing}
            />
          ) : null}

          {!resolvedLayout.hasShownPane ? (
            <div data-testid="desktop-workbench-empty-hint" className="workbench-layout-empty-hint">
              <span>所有窗口都已隐藏，可通过顶部布局开关重新显示。</span>
            </div>
          ) : null}
        </div>
      </div>

      <WorkbenchStatusBar
        activeFilePath={tabs.activeTab?.kind === "external-source"
          ? `外部依赖 · 只读${tabs.activeTab.displayPath ? ` / ${tabs.activeTab.displayPath}` : ""}`
          : tabs.activeTab?.path || ""}
        fileDirty={Boolean(tabs.activeTab?.dirty)}
        terminalStatus={terminalStatus}
        chatStatus={externalChatStatus || localChatStatus}
        debugStatus={remoteWorkspace ? { phase: "idle", connectionText: "" } : debug.statusBar}
        restoreState={session.restoreState}
        branchName={gitBranchName}
        viewMode={viewMode}
        languageServiceProvider={languageService.provider}
        languageServiceStatus={languageService.status}
        languageServiceLoading={languageService.loading}
        languageServiceRestarting={isRestartingLanguageService}
        languageServiceRestartError={languageServerRestartError}
        onRestartLanguageService={canRestartLanguageService ? restartCurrentLanguageService : undefined}
        rightAction={(
          <div className="flex items-center gap-2">
            {fileTree.uploadProgress ? (
              <WorkbenchTransferStatus
                verb="上传"
                target={fileTree.uploadProgress.fileCount > 1
                  ? `${fileTree.uploadProgress.filename} (${fileTree.uploadProgress.fileIndex}/${fileTree.uploadProgress.fileCount})`
                  : fileTree.uploadProgress.filename}
                transferredBytes={fileTree.uploadProgress.uploadedBytes}
                totalBytes={fileTree.uploadProgress.totalBytes}
                percent={fileTree.uploadProgress.percent}
                awaitingServer={fileTree.uploadProgress.percent === 100}
                onCancel={fileTree.cancelUpload}
              />
            ) : null}
            {fileTree.downloadProgress ? (
              <WorkbenchTransferStatus
                verb="下载"
                target={fileTree.downloadProgress.path}
                transferredBytes={fileTree.downloadProgress.downloadedBytes}
                totalBytes={fileTree.downloadProgress.totalBytes}
                percent={fileTree.downloadProgress.percent}
                onCancel={fileTree.cancelDownload}
              />
            ) : null}
            {lanChatDock}
          </div>
        )}
      />

      {!structureOnly && !remoteWorkspace ? (
        <CommandPalette
          open={commandPaletteOpen}
          botAlias={botAlias}
          client={client}
          disabled={structureOnly}
          canNavigateDefinition={allowCodeJump && (tabs.activeTab?.kind === "file" || tabs.activeTab?.kind === "external-source")}
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

      {definitionCandidates.length > 0 || definitionMessage ? (
        <div className="absolute inset-0 z-30 flex items-start justify-center bg-[var(--overlay-backdrop-35)] px-4 py-12">
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
