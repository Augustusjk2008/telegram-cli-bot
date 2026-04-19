import type { ViewMode } from "../app/layoutMode";
import type {
  ChatWorkbenchStatus,
  TerminalWorkbenchStatus,
  WorkbenchRestoreState,
} from "./workbenchTypes";

type Props = {
  activeFilePath: string;
  fileDirty: boolean;
  terminalStatus: TerminalWorkbenchStatus;
  chatStatus: ChatWorkbenchStatus;
  restoreState: WorkbenchRestoreState;
  branchName?: string;
  viewMode: ViewMode;
};

function viewModeLabel(viewMode: ViewMode) {
  if (viewMode === "desktop") {
    return "桌面版";
  }
  if (viewMode === "mobile") {
    return "手机版";
  }
  return "自动";
}

function chatLabel(status: ChatWorkbenchStatus) {
  if (status.state === "error") {
    return "AI 错误";
  }
  if (status.processing) {
    return typeof status.elapsedSeconds === "number" ? `AI 运行 ${status.elapsedSeconds}s` : "AI 运行中";
  }
  if (status.state === "waiting") {
    return "AI 等待中";
  }
  return "AI 空闲";
}

function restoreLabel(state: WorkbenchRestoreState) {
  if (state === "draft-only") {
    return "已恢复草稿";
  }
  if (state === "restored") {
    return "已恢复会话";
  }
  return "新会话";
}

export function WorkbenchStatusBar({
  activeFilePath,
  fileDirty,
  terminalStatus,
  chatStatus,
  restoreState,
  branchName = "",
  viewMode,
}: Props) {
  return (
    <footer
      data-testid="desktop-workbench-statusbar"
      className="flex items-center justify-between gap-3 border-t border-[var(--workbench-hairline)] bg-[var(--workbench-statusbar-bg)] px-3 py-1.5 text-xs text-[var(--text)]"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="truncate font-mono">{activeFilePath || "未打开文件"}</span>
        <span>{fileDirty ? "未保存" : "已保存"}</span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span>{terminalStatus.connectionText}</span>
        <span className="max-w-[24rem] truncate font-mono">{terminalStatus.overrideCwd || terminalStatus.currentCwd}</span>
        {branchName ? <span className="font-mono">{branchName}</span> : null}
        <span>{chatLabel(chatStatus)}</span>
        <span>{restoreLabel(restoreState)}</span>
        <span>{viewModeLabel(viewMode)}</span>
      </div>
    </footer>
  );
}
