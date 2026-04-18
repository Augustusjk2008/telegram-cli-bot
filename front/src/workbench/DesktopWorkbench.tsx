import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ViewMode } from "../app/layoutMode";
import type { WebBotClient } from "../services/webBotClient";
import type { UiThemeName } from "../theme";
import { ChatPane } from "./ChatPane";
import { EditorPane } from "./EditorPane";
import { FileTreePane } from "./FileTreePane";
import { PaneChrome } from "./PaneChrome";
import { PaneResizer } from "./PaneResizer";
import { TerminalPane } from "./TerminalPane";
import { WorkbenchActivityRail } from "./WorkbenchActivityRail";
import { useEditorTabs } from "./useEditorTabs";
import { useFileBrowser } from "./useFileBrowser";
import { WorkbenchHeader } from "./WorkbenchHeader";
import { WorkbenchStatusBar } from "./WorkbenchStatusBar";
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
  onViewModeChange,
  onOpenBotSwitcher,
  onDirtyTabsChange,
}: Props) {
  const { paneState, togglePane, resizePane } = useWorkbenchState();
  const browser = useFileBrowser({ botAlias, client });
  const tabs = useEditorTabs({ botAlias, client });
  const columnsRef = useRef<HTMLDivElement | null>(null);
  const centerRowsRef = useRef<HTMLDivElement | null>(null);
  const [layoutBounds, setLayoutBounds] = useState({
    columnsWidthPx: 1440,
    centerHeightPx: 900,
  });

  const layoutState = clampPaneState(paneState, {
    containerWidthPx: layoutBounds.columnsWidthPx,
    containerHeightPx: layoutBounds.centerHeightPx,
  });

  const columnTemplate = layoutState.filesCollapsed
    ? `${COLLAPSED_SIDEBAR_SIZE_PX}px ${PANE_RESIZER_SIZE_PX}px minmax(0, 1fr) ${PANE_RESIZER_SIZE_PX}px ${layoutState.chatCollapsed ? COLLAPSED_SIDEBAR_SIZE_PX : layoutState.chatWidthPx}px`
    : `${layoutState.filesWidthPx}px ${PANE_RESIZER_SIZE_PX}px minmax(0, 1fr) ${PANE_RESIZER_SIZE_PX}px ${layoutState.chatCollapsed ? COLLAPSED_SIDEBAR_SIZE_PX : layoutState.chatWidthPx}px`;

  const centerRowTemplate = layoutState.editorCollapsed
    ? `auto ${PANE_RESIZER_SIZE_PX}px minmax(0, 1fr)`
    : `${layoutState.editorHeightPx}px ${PANE_RESIZER_SIZE_PX}px minmax(${MIN_TERMINAL_HEIGHT_PX}px, 1fr)`;
  const workspaceName = browser.currentPath.split(/[\\/]+/).filter(Boolean).pop() || browser.currentPath || "/";

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

  return (
    <div
      data-testid="desktop-workbench-root"
      className="grid h-[100dvh] min-h-0 w-full grid-rows-[auto_minmax(0,1fr)_auto] bg-[var(--bg)]"
    >
      <WorkbenchHeader
        currentBot={botAlias}
        workspaceName={workspaceName}
        viewMode={viewMode}
        onViewModeChange={(nextMode) => onViewModeChange?.(nextMode)}
        onOpenBotSwitcher={() => onOpenBotSwitcher?.()}
      />
      <div data-testid="desktop-workbench-shell" className="min-h-0">
        <div
          data-testid="desktop-workbench-columns"
          ref={columnsRef}
          className={clsx("grid min-h-0 p-3")}
          style={{ gridTemplateColumns: columnTemplate }}
        >
          <section
            data-testid="desktop-pane-files"
            data-collapsed={layoutState.filesCollapsed ? "true" : "false"}
            className="grid min-h-0 border border-[var(--border)] bg-[var(--surface)]"
          >
            <div
              className={
                layoutState.filesCollapsed ? "grid min-h-0 grid-cols-[1fr]" : "grid min-h-0 grid-cols-[48px_minmax(0,1fr)]"
              }
            >
              <WorkbenchActivityRail
                activePanel="explorer"
                explorerCollapsed={layoutState.filesCollapsed}
                onToggleExplorer={() => togglePane("files")}
              />
              {!layoutState.filesCollapsed ? (
                <FileTreePane
                  browser={browser}
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
                />
              ) : null}
            </div>
          </section>
          <PaneResizer
            ariaLabel="调整文件区宽度"
            axis="x"
            onResizeDelta={(deltaPx) =>
              resizePane("filesWidthPx", layoutState.filesWidthPx + deltaPx, {
                containerWidthPx: layoutBounds.columnsWidthPx,
                containerHeightPx: layoutBounds.centerHeightPx,
              })}
          />

          <div
            data-testid="desktop-workbench-center-rows"
            ref={centerRowsRef}
            className="grid min-h-0"
            style={{ gridTemplateRows: centerRowTemplate }}
          >
            <PaneChrome
              testId="desktop-pane-editor"
              title="编辑器"
              collapsed={layoutState.editorCollapsed}
              collapseLabel="折叠编辑区"
              expandLabel="展开编辑区"
              onToggleCollapsed={() => togglePane("editor")}
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
            </PaneChrome>
            <PaneResizer
              ariaLabel="调整编辑器高度"
              axis="y"
              onResizeDelta={(deltaPx) =>
                resizePane("editorHeightPx", layoutState.editorHeightPx + deltaPx, {
                  containerWidthPx: layoutBounds.columnsWidthPx,
                  containerHeightPx: layoutBounds.centerHeightPx,
                })}
            />
            <PaneChrome
              testId="desktop-pane-terminal"
              title="终端"
              collapsed={layoutState.terminalCollapsed}
              collapseLabel="折叠终端区"
              expandLabel="展开终端区"
              onToggleCollapsed={() => togglePane("terminal")}
            >
              <TerminalPane
                authToken={authToken}
                botAlias={botAlias}
                client={client}
                preferredWorkingDir={browser.currentPath}
                themeName={themeName}
              />
            </PaneChrome>
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

          <PaneChrome
            testId="desktop-pane-chat"
            title="AI 聊天"
            collapsed={layoutState.chatCollapsed}
            collapseLabel="折叠右侧聊天区"
            expandLabel="展开右侧聊天区"
            onToggleCollapsed={() => togglePane("chat")}
          >
            <ChatPane
              botAlias={botAlias}
              botAvatarName={botAvatarName}
              userAvatarName={userAvatarName}
              client={client}
            />
          </PaneChrome>
        </div>
      </div>
      <WorkbenchStatusBar
        currentPath={browser.currentPath}
        activeFilePath={tabs.activeTab?.path || ""}
        isDirty={Boolean(tabs.activeTab?.dirty)}
        terminalLabel="终端"
        chatLabel="AI 助手"
        viewMode={viewMode}
      />
    </div>
  );
}
