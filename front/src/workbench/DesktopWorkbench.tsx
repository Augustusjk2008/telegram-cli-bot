import { clsx } from "clsx";
import { useEffect } from "react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ViewMode } from "../app/layoutMode";
import type { WebBotClient } from "../services/webBotClient";
import type { UiThemeName } from "../theme";
import { ChatPane } from "./ChatPane";
import { EditorPane } from "./EditorPane";
import { FileTreePane } from "./FileTreePane";
import { PaneChrome } from "./PaneChrome";
import { TerminalPane } from "./TerminalPane";
import { useEditorTabs } from "./useEditorTabs";
import { useFileBrowser } from "./useFileBrowser";
import { WorkbenchHeader } from "./WorkbenchHeader";
import { useWorkbenchState } from "./useWorkbenchState";

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
  const { paneState, togglePane } = useWorkbenchState();
  const browser = useFileBrowser({ botAlias, client });
  const tabs = useEditorTabs({ botAlias, client });

  useEffect(() => {
    onDirtyTabsChange?.(tabs.hasDirtyTabs);
  }, [onDirtyTabsChange, tabs.hasDirtyTabs]);

  return (
    <div data-testid="desktop-workbench-root" className="grid h-[100dvh] min-h-0 w-full grid-rows-[auto_minmax(0,1fr)] bg-[var(--bg)]">
      <WorkbenchHeader
        currentBot={botAlias}
        viewMode={viewMode}
        onViewModeChange={(nextMode) => onViewModeChange?.(nextMode)}
        onOpenBotSwitcher={() => onOpenBotSwitcher?.()}
      />
      <div
        className={clsx(
          "grid min-h-0 gap-3 p-3",
          paneState.filesCollapsed && paneState.chatCollapsed
            ? "grid-cols-[4.5rem_minmax(0,1fr)_4.5rem]"
            : paneState.filesCollapsed
              ? "grid-cols-[4.5rem_minmax(0,1fr)_24rem]"
              : paneState.chatCollapsed
                ? "grid-cols-[20rem_minmax(0,1fr)_4.5rem]"
                : "grid-cols-[20rem_minmax(0,1fr)_24rem]",
        )}
      >
        <PaneChrome
          testId="desktop-pane-files"
          title="文件"
          collapsed={paneState.filesCollapsed}
          collapseLabel="折叠左侧文件区"
          expandLabel="展开左侧文件区"
          onToggleCollapsed={() => togglePane("files")}
        >
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
        </PaneChrome>

        <div
          className={clsx(
            "grid min-h-0 gap-3",
            paneState.editorCollapsed && paneState.terminalCollapsed
              ? "grid-rows-[auto_auto]"
              : paneState.editorCollapsed
                ? "grid-rows-[auto_minmax(0,1fr)]"
                : paneState.terminalCollapsed
                  ? "grid-rows-[minmax(0,1fr)_auto]"
                  : "grid-rows-[minmax(0,1fr)_minmax(16rem,0.72fr)]",
          )}
        >
          <PaneChrome
            testId="desktop-pane-editor"
            title="编辑器"
            collapsed={paneState.editorCollapsed}
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
          <PaneChrome
            testId="desktop-pane-terminal"
            title="终端"
            collapsed={paneState.terminalCollapsed}
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

        <PaneChrome
          testId="desktop-pane-chat"
          title="AI 聊天"
          collapsed={paneState.chatCollapsed}
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
  );
}
