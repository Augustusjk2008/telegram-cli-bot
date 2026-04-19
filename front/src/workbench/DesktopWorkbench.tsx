import { clsx } from "clsx";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ViewMode } from "../app/layoutMode";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { WebBotClient } from "../services/webBotClient";
import { GitScreen } from "../screens/GitScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import type { UiThemeName } from "../theme";
import { ChatPane } from "./ChatPane";
import { EditorPane } from "./EditorPane";
import { FileTreePane } from "./FileTreePane";
import { PaneResizer } from "./PaneResizer";
import { TerminalPane } from "./TerminalPane";
import { WorkbenchActivityRail } from "./WorkbenchActivityRail";
import { WorkbenchHeader } from "./WorkbenchHeader";
import { useEditorTabs } from "./useEditorTabs";
import { useFileTree } from "./useFileTree";
import { useWorkbenchState } from "./useWorkbenchState";
import { clampPaneState, COLLAPSED_SIDEBAR_SIZE_PX, MIN_TERMINAL_HEIGHT_PX, PANE_RESIZER_SIZE_PX } from "./workbenchTypes";

type Props = {
  authToken?: string;
  botAlias: string;
  botAvatarName?: string;
  userAvatarName?: string;
  client?: WebBotClient;
  themeName?: UiThemeName;
  viewMode?: ViewMode;
  hasUnreadOtherBots?: boolean;
  chatPaneContent?: ReactNode;
  onUnreadResult?: (botAlias: string) => void;
  onViewModeChange?: (viewMode: ViewMode) => void;
  onOpenBotSwitcher?: () => void;
  onDirtyTabsChange?: (hasDirtyTabs: boolean) => void;
};

export function DesktopWorkbench({
  authToken = "",
  botAvatarName,
  client = new MockWebBotClient(),
  botAlias,
  userAvatarName,
  themeName,
  viewMode = "desktop",
  hasUnreadOtherBots = false,
  chatPaneContent,
  onUnreadResult,
  onViewModeChange,
  onOpenBotSwitcher,
  onDirtyTabsChange,
}: Props) {
  const { paneState, toggleSidebar, setSidebarView, resizePane } = useWorkbenchState();
  const fileTree = useFileTree(botAlias, client);
  const tabs = useEditorTabs({ botAlias, client });
  const columnsRef = useRef<HTMLDivElement | null>(null);
  const centerRowsRef = useRef<HTMLDivElement | null>(null);
  const [layoutBounds, setLayoutBounds] = useState({
    columnsWidthPx: 1440,
    centerHeightPx: 900,
  });
  const [pendingSidebarWorkdir, setPendingSidebarWorkdir] = useState("");

  const layoutState = clampPaneState(paneState, {
    containerWidthPx: layoutBounds.columnsWidthPx,
    containerHeightPx: layoutBounds.centerHeightPx,
  });

  const columnTemplate = `${layoutState.sidebarCollapsed ? COLLAPSED_SIDEBAR_SIZE_PX : layoutState.sidebarWidthPx}px ${PANE_RESIZER_SIZE_PX}px minmax(0, 1fr) ${PANE_RESIZER_SIZE_PX}px ${layoutState.chatWidthPx}px`;
  const centerRowTemplate = `${layoutState.editorHeightPx}px ${PANE_RESIZER_SIZE_PX}px minmax(${MIN_TERMINAL_HEIGHT_PX}px, 1fr)`;
  const workspaceName = fileTree.rootPath.split(/[\\/]+/).filter(Boolean).pop() || fileTree.rootPath || "/";

  useEffect(() => {
    onDirtyTabsChange?.(tabs.hasDirtyTabs);
  }, [onDirtyTabsChange, tabs.hasDirtyTabs]);

  useEffect(() => {
    const updateLayoutBounds = () => {
      const nextColumnsWidthPx = columnsRef.current?.getBoundingClientRect().width ?? 0;
      const nextCenterHeightPx = centerRowsRef.current?.getBoundingClientRect().height ?? 0;

      setLayoutBounds((current) => ({
        columnsWidthPx: nextColumnsWidthPx > 0 ? nextColumnsWidthPx : current.columnsWidthPx,
        centerHeightPx: nextCenterHeightPx > 0 ? nextCenterHeightPx : current.centerHeightPx,
      }));
    };

    updateLayoutBounds();
    window.addEventListener("resize", updateLayoutBounds);
    return () => {
      window.removeEventListener("resize", updateLayoutBounds);
    };
  }, []);

  function renderSidebarContent() {
    if (layoutState.sidebarView === "git") {
      return <GitScreen botAlias={botAlias} botAvatarName={botAvatarName} client={client} embedded />;
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
            void fileTree.refreshRoot();
          }}
          themeName={themeName}
          userAvatarName={userAvatarName}
        />
      );
    }

    return (
      <FileTreePane
        tree={fileTree}
        onOpenFile={(path) => {
          void tabs.openFile(path);
        }}
        onCreatedFile={(path, content, lastModifiedNs) => {
          tabs.openCreatedFile(path, content, lastModifiedNs);
        }}
        onRenamedFile={(oldPath, nextPath) => {
          tabs.syncRenamedPath(oldPath, nextPath);
        }}
        onDeletedFile={(path) => {
          tabs.closePath(path);
        }}
        onRequestSetWorkdir={(path) => {
          setPendingSidebarWorkdir(path);
          setSidebarView("settings");
        }}
      />
    );
  }

  return (
    <div
      data-testid="desktop-workbench-root"
      className="grid h-[100dvh] min-h-0 w-full grid-rows-[auto_minmax(0,1fr)] bg-[var(--bg)]"
    >
      <WorkbenchHeader
        currentBot={botAlias}
        workspaceName={workspaceName}
        viewMode={viewMode}
        hasUnreadOtherBots={hasUnreadOtherBots}
        onViewModeChange={(nextMode) => onViewModeChange?.(nextMode)}
        onOpenBotSwitcher={() => onOpenBotSwitcher?.()}
      />

      <div data-testid="desktop-workbench-shell" className="min-h-0 overflow-hidden">
        <div
          data-testid="desktop-workbench-columns"
          ref={columnsRef}
          className="grid h-full min-h-0 p-3"
          style={{ gridTemplateColumns: columnTemplate }}
        >
          <section
            data-testid="desktop-pane-files"
            data-collapsed={layoutState.sidebarCollapsed ? "true" : "false"}
            className="grid min-h-0 overflow-hidden border border-[var(--border)] bg-[var(--surface)]"
          >
            <div
              className={clsx(
                "grid min-h-0",
                layoutState.sidebarCollapsed ? "grid-cols-[48px]" : "grid-cols-[48px_minmax(0,1fr)]",
              )}
            >
              <WorkbenchActivityRail
                activePanel={layoutState.sidebarView}
                sidebarCollapsed={layoutState.sidebarCollapsed}
                onToggleSidebar={toggleSidebar}
                onSelectPanel={setSidebarView}
              />

              {!layoutState.sidebarCollapsed ? (
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
            <section
              data-testid="desktop-pane-editor"
              className="min-h-0 overflow-hidden border border-[var(--border)] bg-[var(--surface)]"
            >
              <EditorPane
                tabs={tabs.tabs}
                activeTab={tabs.activeTab}
                activeTabPath={tabs.activeTabPath}
                onActivateTab={tabs.activateTab}
                onCloseTab={tabs.closeTab}
                onChangeActiveContent={tabs.updateActiveContent}
                onSaveActiveTab={() => void tabs.saveActiveTab()}
              />
            </section>

            <PaneResizer
              ariaLabel="调整编辑器高度"
              axis="y"
              onResizeDelta={(deltaPx) =>
                resizePane("editorHeightPx", layoutState.editorHeightPx + deltaPx, {
                  containerWidthPx: layoutBounds.columnsWidthPx,
                  containerHeightPx: layoutBounds.centerHeightPx,
                })}
            />

            <section
              data-testid="desktop-pane-terminal"
              className="min-h-0 overflow-hidden border border-[var(--border)] bg-[var(--surface)]"
            >
              <TerminalPane
                authToken={authToken}
                botAlias={botAlias}
                client={client}
                preferredWorkingDir={fileTree.rootPath}
                themeName={themeName}
              />
            </section>
          </div>

          <PaneResizer
            ariaLabel="调整聊天区宽度"
            axis="x"
            onResizeDelta={(deltaPx) =>
              resizePane("chatWidthPx", layoutState.chatWidthPx - deltaPx, {
                containerWidthPx: layoutBounds.columnsWidthPx,
                containerHeightPx: layoutBounds.centerHeightPx,
              })}
          />

          <section
            data-testid="desktop-pane-chat"
            className="min-h-0 overflow-hidden border border-[var(--border)] bg-[var(--surface)]"
          >
            {chatPaneContent || (
              <ChatPane
                botAlias={botAlias}
                botAvatarName={botAvatarName}
                userAvatarName={userAvatarName}
                client={client}
                onUnreadResult={onUnreadResult}
              />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
