import { clsx } from "clsx";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import type { ViewMode } from "../app/layoutMode";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileReadResult, GitTreeStatus, WorkspaceDefinitionItem } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { GitScreen } from "../screens/GitScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import "../styles/workbench.css";
import type {
  ChatBodyFontFamilyName,
  ChatBodyFontSizeName,
  ChatBodyLineHeightName,
  ChatBodyParagraphSpacingName,
  UiThemeName,
} from "../theme";
import { getFilePreviewStatusText, isFilePreviewFullyLoaded, isFilePreviewTooLarge } from "../utils/filePreview";
import { ChatPane } from "./ChatPane";
import { CommandPalette } from "./CommandPalette";
import { DebugPane } from "./DebugPane";
import { EditorPane } from "./EditorPane";
import { FileTreePane } from "./FileTreePane";
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
import {
  clampPaneState,
  COLLAPSED_SIDEBAR_SIZE_PX,
  MIN_TERMINAL_HEIGHT_PX,
  PANE_RESIZER_SIZE_PX,
  type ChatWorkbenchStatus,
  type FocusedWorkbenchPane,
  type TerminalOverrideState,
  type TerminalWorkbenchStatus,
} from "./workbenchTypes";

type Props = {
  authToken?: string;
  botAlias: string;
  botAvatarName?: string;
  userAvatarName?: string;
  client?: WebBotClient;
  structureOnly?: boolean;
  chatReadOnly?: boolean;
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
  viewMode?: ViewMode;
  hasUnreadOtherBots?: boolean;
  chatPaneContent?: ReactNode;
  chatStatus?: ChatWorkbenchStatus;
  onUnreadResult?: (botAlias: string) => void;
  onViewModeChange?: (viewMode: ViewMode) => void;
  onOpenBotSwitcher?: () => void;
  onDirtyTabsChange?: (hasDirtyTabs: boolean) => void;
  onChatPaneVisibilityChange?: (visible: boolean) => void;
};

export function DesktopWorkbench({
  authToken = "",
  botAvatarName,
  client = new MockWebBotClient(),
  botAlias,
  userAvatarName,
  structureOnly = false,
  chatReadOnly = false,
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
  viewMode = "desktop",
  hasUnreadOtherBots = false,
  chatPaneContent,
  chatStatus: externalChatStatus,
  onUnreadResult,
  onViewModeChange,
  onOpenBotSwitcher,
  onDirtyTabsChange,
  onChatPaneVisibilityChange,
}: Props) {
  const { paneState, toggleSidebar, toggleTerminal, toggleChat, setSidebarView, resizePane } = useWorkbenchState();
  const fileTree = useFileTree(botAlias, client, { structureOnly });
  const tabs = useEditorTabs({ botAlias, client });
  const columnsRef = useRef<HTMLDivElement | null>(null);
  const centerRowsRef = useRef<HTMLDivElement | null>(null);
  const editorPaneRef = useRef<HTMLElement | null>(null);
  const restoringRef = useRef(false);
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
  const [focusedPane, setFocusedPane] = useState<FocusedWorkbenchPane>(null);
  const [terminalOverride, setTerminalOverride] = useState<TerminalOverrideState | null>(null);
  const [pendingTerminalOverride, setPendingTerminalOverride] = useState<TerminalOverrideState | null>(null);
  const [localChatStatus, setLocalChatStatus] = useState<ChatWorkbenchStatus>({
    state: "idle",
    processing: false,
  });
  const [terminalStatus, setTerminalStatus] = useState<TerminalWorkbenchStatus>({
    connected: false,
    connectionText: "准备启动",
    currentCwd: "",
  });
  const [gitBranchName, setGitBranchName] = useState("");
  const [gitDecorations, setGitDecorations] = useState<GitTreeStatus["items"]>({});
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [editorReveal, setEditorReveal] = useState<{ path: string; line: number } | null>(null);
  const [definitionCandidates, setDefinitionCandidates] = useState<WorkspaceDefinitionItem[]>([]);
  const [definitionMessage, setDefinitionMessage] = useState("");
  const [definitionSource, setDefinitionSource] = useState("");
  const gitDecorationRequestRef = useRef(0);

  const layoutState = clampPaneState(paneState, {
    containerWidthPx: layoutBounds.columnsWidthPx,
    containerHeightPx: layoutBounds.centerHeightPx,
  });
  const debug = useDebugSession({
    authToken,
    botAlias,
    client,
    enabled: !structureOnly && layoutState.sidebarView === "debug",
    onRevealLocation: ({ sourcePath }) => {
      void tabs.openFile(sourcePath);
    },
  });

  const session = useWorkbenchSession({
    botAlias,
    workspaceRoot: fileTree.rootPath,
    snapshot: fileTree.rootPath
      ? {
          sidebarView: layoutState.sidebarView,
          expandedPaths: fileTree.expandedPaths,
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
  const previewStatusText = getFilePreviewStatusText(previewResult);
  const canLoadFull = !isFilePreviewFullyLoaded(previewResult) && !isFilePreviewTooLarge(previewResult?.fileSizeBytes);
  const showSidebarContent = focusedPane === "sidebar" || !layoutState.sidebarCollapsed;
  const availableSidebarPanels = structureOnly
    ? ["files"] as const
    : ["files", "search", "outline", "debug", "git", "settings"] as const;
  const activeEditorLine = tabs.activeTab && editorReveal?.path === tabs.activeTab.path
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
    } catch {
      if (gitDecorationRequestRef.current !== requestId) {
        return;
      }
      setGitDecorations({});
    }
  }, [botAlias, client]);

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
    if (!fileTree.rootPath || session.restoreApplied || restoringRef.current) {
      return;
    }

    restoringRef.current = true;
    let cancelled = false;

    void (async () => {
      try {
        const restoredSession = session.restoredSession;
        if (restoredSession) {
          setSidebarView(restoredSession.sidebarView);
          setFocusedPane(restoredSession.focusedPane ?? null);
          setTerminalOverride(restoredSession.terminalOverrideCwd
            ? { cwd: restoredSession.terminalOverrideCwd, source: "manual" }
            : null);
          await fileTree.restoreExpandedPaths(restoredSession.expandedPaths);
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
  }, [fileTree.rootPath, session.restoreApplied, session.restoredSession]);

  useEffect(() => {
    if (!fileTree.rootPath) {
      setGitBranchName("");
      setGitDecorations({});
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
  }, [setSidebarView, structureOnly]);

  function toggleFocusedPane(nextPane: Exclude<FocusedWorkbenchPane, null>) {
    setFocusedPane((current) => current === nextPane ? null : nextPane);
  }

  async function loadPreview(path: string, mode: "preview" | "full") {
    setPreviewLoading(true);
    try {
      const result = mode === "full"
        ? await client.readFileFull(botAlias, path)
        : await client.readFile(botAlias, path);
      setPreviewName(path);
      setPreviewMode(result.mode === "cat" ? "full" : "preview");
      setPreviewResult(result);
      setPreviewContent(result.content || "文件为空");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function openWorkspaceFile(path: string, line?: number) {
    await Promise.allSettled([
      tabs.openFile(path),
      fileTree.revealPath(path),
    ]);
    if (line && line > 0) {
      setEditorReveal({ path, line });
      return;
    }
    setEditorReveal(null);
  }

  async function openGitDiffInEditor(path: string, staged: boolean) {
    const diff = await client.getGitDiff(botAlias, path, staged);
    const basename = path.split(/[\\/]/).filter(Boolean).pop() || path;
    const tabPath = `git-diff:${staged ? "staged" : "worktree"}:${path}`;
    tabs.openReadOnlyTab({
      path: tabPath,
      basename: `${basename}.diff`,
      content: diff.diff || "当前没有可显示的差异",
      sourcePath: path,
      kind: "git-diff",
      statusText: `${path} · ${staged ? "已暂存" : "工作区"} Diff · 只读`,
    });
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
    for (const file of files) {
      await client.uploadFile(botAlias, file);
      fileTree.highlightPath(file.name);
    }
    await fileTree.refreshRoot({ preserveExpandedPaths: true });
    await refreshGitDecorations();
  }

  function renderSidebarContent() {
    if (structureOnly || layoutState.sidebarView === "files") {
      return (
        <FileTreePane
          tree={fileTree}
          onOpenFile={(path) => {
            void tabs.openFile(path);
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
          onRequestUpload={handleUpload}
          gitDecorations={gitDecorations}
          onRefreshGitDecorations={refreshGitDecorations}
          onRequestSetWorkdir={(path) => {
            setPendingSidebarWorkdir(path);
            setSidebarView("settings");
          }}
          structureOnly={structureOnly}
          focused={focusedPane === "sidebar"}
          onToggleFocus={() => toggleFocusedPane("sidebar")}
        />
      );
    }

    if (layoutState.sidebarView === "search") {
      return (
        <SearchPane
          botAlias={botAlias}
          client={client}
          onOpenFile={openWorkspaceFile}
        />
      );
    }

    if (layoutState.sidebarView === "outline") {
      return (
        <OutlinePane
          botAlias={botAlias}
          client={client}
          activeFilePath={tabs.activeTab?.path || ""}
          onOpenFile={openWorkspaceFile}
        />
      );
    }

    if (layoutState.sidebarView === "debug") {
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

    if (layoutState.sidebarView === "git") {
      return (
        <GitScreen
          botAlias={botAlias}
          botAvatarName={botAvatarName}
          client={client}
          embedded
          onOpenDiff={openGitDiffInEditor}
          onOverviewChange={(overview) => {
            setGitBranchName(overview?.repoFound ? overview.currentBranch : "");
            void refreshGitDecorations();
          }}
        />
      );
    }

    if (layoutState.sidebarView === "settings") {
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
            void fileTree.refreshRoot({ preserveExpandedPaths: true });
            void refreshGitDecorations();
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
        />
      );
    }
  }

  return (
    <div
      data-testid="desktop-workbench-root"
      data-restore-state={session.restoreState}
      data-has-focus={focusedPane ? "true" : "false"}
      data-focused-pane={focusedPane || "none"}
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
        sidebarVisible={!layoutState.sidebarCollapsed}
        terminalVisible={!structureOnly && !layoutState.terminalCollapsed}
        chatVisible={!layoutState.chatCollapsed}
        availableLayoutControls={structureOnly ? ["sidebar", "chat"] : undefined}
        onToggleSidebar={toggleSidebar}
        onToggleTerminal={toggleTerminal}
        onToggleChat={toggleChat}
        onViewModeChange={(nextMode) => onViewModeChange?.(nextMode)}
        onOpenBotSwitcher={() => onOpenBotSwitcher?.()}
      />

      <div data-testid="desktop-workbench-shell" className="min-h-0 overflow-hidden">
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
                activePanel={layoutState.sidebarView}
                sidebarCollapsed={layoutState.sidebarCollapsed}
                availablePanels={[...availableSidebarPanels]}
                onToggleSidebar={toggleSidebar}
                onSelectPanel={setSidebarView}
              />

              {showSidebarContent ? (
                layoutState.sidebarView === "files" ? (
                  renderSidebarContent()
                ) : (
                  <div data-testid="desktop-sidebar-scroll" className="min-h-0 overflow-y-auto">
                    {renderSidebarContent()}
                  </div>
                )
              ) : null}
            </div>
          </section>

          <PaneResizer
            ariaLabel="调整文件区宽度"
            axis="x"
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
                <EditorPane
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
                  focused={focusedPane === "editor"}
                  onToggleFocus={() => toggleFocusedPane("editor")}
                />
              </section>
            ) : null}

            {!structureOnly && !focusedPane && showTerminalPane ? (
              <PaneResizer
                ariaLabel="调整编辑器高度"
                axis="y"
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
                <TerminalPane
                  authToken={authToken}
                  botAlias={botAlias}
                  client={client}
                  preferredWorkingDir={terminalOverride?.cwd || fileTree.rootPath}
                  pendingWorkingDir={pendingTerminalOverride?.cwd}
                  themeName={themeName}
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

          {!focusedPane && showChatPane ? (
            <PaneResizer
              ariaLabel="调整聊天区宽度"
              axis="x"
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
            {chatPaneContent || (
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
      />

      {!structureOnly ? (
        <CommandPalette
          open={commandPaletteOpen}
          botAlias={botAlias}
          client={client}
          onClose={() => setCommandPaletteOpen(false)}
          onOpenFile={openWorkspaceFile}
        />
      ) : null}

      {previewName ? (
        <FilePreviewDialog
          title={previewName}
          content={previewContent}
          mode={previewMode}
          variant="desktop"
          desktopAnchorRect={editorPaneBounds}
          loading={previewLoading}
          statusText={previewStatusText}
          onClose={() => {
            setPreviewName("");
            setPreviewContent("");
            setPreviewResult(null);
          }}
          onLoadFull={previewMode !== "full" && canLoadFull ? () => void loadPreview(previewName, "full") : undefined}
          onEdit={() => {
            const nextPath = previewName;
            setPreviewName("");
            setPreviewContent("");
            setPreviewResult(null);
            void tabs.openFile(nextPath);
          }}
          onDownload={() => void client.downloadFile(botAlias, previewName)}
        />
      ) : null}

      {definitionCandidates.length > 0 || definitionMessage ? (
        <div className="absolute inset-0 z-30 flex items-start justify-center bg-black/35 px-4 py-12">
          <div
            data-testid="desktop-definition-picker"
            className="w-full max-w-2xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl"
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
          </div>
        </div>
      ) : null}
    </div>
  );
}
