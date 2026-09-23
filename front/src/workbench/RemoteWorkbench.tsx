import { useState, type ReactNode } from "react";
import type { ViewMode } from "../app/layoutMode";
import type { BotSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import type { UiThemeName } from "../theme";
import { workspaceLabel } from "../services/remoteWorkspace";
import { RemoteFilesPane } from "../components/RemoteFilesPane";
import { TerminalTabsScreen } from "../screens/TerminalTabsScreen";
import { WorkbenchHeader } from "./WorkbenchHeader";
import "../styles/workbench.css";

export function RemoteWorkbench({ bot, client, authToken, chat, canWrite, structureOnly, terminalDisabledReason, themeName, viewMode, onViewModeChange, onOpenBotSwitcher, onLogout, onDirtyChange, announcementAction }: {
  bot: BotSummary; client: WebBotClient; authToken: string; chat: ReactNode; canWrite: boolean; structureOnly: boolean;
  terminalDisabledReason: string; themeName: UiThemeName; viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void; onOpenBotSwitcher: (rect?: DOMRect) => void; onLogout: () => void;
  onDirtyChange: (dirty: boolean) => void; announcementAction?: ReactNode;
}) {
  const [terminal, setTerminal] = useState(false);
  const remote = bot.remoteWorkspace!;
  return <div className="flex h-dvh min-h-0 flex-col bg-[var(--bg)] text-[var(--text)]">
    <WorkbenchHeader currentBot={bot.alias} workspaceName={workspaceLabel(bot)} viewMode={viewMode} sidebarVisible editorVisible terminalVisible={terminal} chatVisible availableLayoutControls={["terminal"]} announcementAction={announcementAction} onToggleSidebar={() => {}} onToggleEditor={() => {}} onToggleTerminal={() => setTerminal((prev) => !prev)} onToggleChat={() => {}} onViewModeChange={onViewModeChange} onOpenBotSwitcher={onOpenBotSwitcher} onLogout={onLogout} />
    <p className="border-b border-[var(--border)] px-3 py-1 text-xs text-[var(--muted)]">远程 SSH · 支持聊天、文件树、文本读写和终端。Git、回滚、搜索、语言服务、调试、插件、本地打开和上传暂不可用。</p>
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(360px,42%)]">
      <div className="flex min-h-0 min-w-0 flex-col border-r border-[var(--border)]">
        <div className="min-h-0 flex-1"><RemoteFilesPane key={bot.alias} botAlias={bot.alias} remote={remote} client={client} canWrite={canWrite} canReconnect={bot.canOperate !== false} structureOnly={structureOnly} onDirtyChange={onDirtyChange} /></div>
        {terminal && <div className="h-[38%] min-h-48 border-t border-[var(--border)]"><TerminalTabsScreen authToken={authToken} botAlias={bot.alias} client={client} isVisible preferredWorkingDir={remote.root} remote themeName={themeName} disabledReason={terminalDisabledReason} embedded /></div>}
      </div>
      <div className="min-h-0 min-w-0">{chat}</div>
    </div>
  </div>;
}
