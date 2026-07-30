import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import type { ViewMode } from "../app/layoutMode";
import type { LanguageServerProviderId, LanguageServerProviderStatus } from "../services/types";
import type {
  ChatWorkbenchStatus,
  DebugWorkbenchStatus,
  TerminalWorkbenchStatus,
  WorkbenchRestoreState,
} from "./workbenchTypes";

type Props = {
  activeFilePath: string;
  fileDirty: boolean;
  terminalStatus: TerminalWorkbenchStatus;
  chatStatus: ChatWorkbenchStatus;
  debugStatus: DebugWorkbenchStatus;
  restoreState: WorkbenchRestoreState;
  branchName?: string;
  viewMode: ViewMode;
  languageServiceProvider?: LanguageServerProviderId | null;
  languageServiceStatus?: LanguageServerProviderStatus | null;
  languageServiceLoading?: boolean;
  languageServiceRestarting?: boolean;
  languageServiceRestartError?: string;
  onRestartLanguageService?: () => void | Promise<void>;
  rightAction?: ReactNode;
};

function viewModeLabel(viewMode: ViewMode) {
  if (viewMode === "desktop") {
    return "横屏版";
  }
  if (viewMode === "mobile") {
    return "竖屏版";
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

function debugLocationLabel(status: DebugWorkbenchStatus) {
  if (!status.currentSourcePath || !status.currentLine) {
    return "";
  }
  const basename = status.currentSourcePath.split(/[\\/]/).filter(Boolean).pop() || status.currentSourcePath;
  return `${basename}:${status.currentLine}`;
}

function languageServiceProviderLabel(provider: LanguageServerProviderId) {
  if (provider === "pyright") return "Python";
  if (provider === "typescript") return "TS/JS";
  return "C/C++";
}

function languageServiceLabel(
  provider: LanguageServerProviderId | null | undefined,
  status: LanguageServerProviderStatus | null | undefined,
  loading: boolean,
  restarting: boolean,
) {
  if (!provider) return "";
  const label = languageServiceProviderLabel(provider);
  if (restarting) return `${label} · 重启中`;
  if (loading) return `${label} · 检测中`;
  if (!status) return `${label} · 状态未知`;
  if (status.runtimeState === "starting") return `${label} · 启动中`;
  if (status.runtimeState === "indexing") return `${label} · 索引中`;
  if (status.runtimeState === "restarting") return `${label} · 重启中`;
  if (status.runtimeState === "degraded") return `${label} · 降级`;
  if (status.runtimeState === "error") return `${label} · 错误`;
  if (status.runtimeState === "stopped") return `${label} · 已停止`;
  if (status.status === "available") {
    return `${label} · 就绪`;
  }
  if (status.status === "installing") return `${label} · 安装中`;
  if (status.status === "missing") return `${label} · 缺失${status.canInstall ? "（可由管理员在设置安装）" : ""}`;
  return `${label} · 错误`;
}

export function WorkbenchStatusBar({
  activeFilePath,
  fileDirty,
  terminalStatus,
  chatStatus,
  debugStatus,
  restoreState,
  branchName = "",
  viewMode,
  languageServiceProvider = null,
  languageServiceStatus = null,
  languageServiceLoading = false,
  languageServiceRestarting = false,
  languageServiceRestartError = "",
  onRestartLanguageService,
  rightAction,
}: Props) {
  const debugLocation = debugLocationLabel(debugStatus);
  const languageService = languageServiceLabel(
    languageServiceProvider,
    languageServiceStatus,
    languageServiceLoading,
    languageServiceRestarting,
  );
  const languageServiceRestartInProgress = languageServiceRestarting
    || languageServiceStatus?.runtimeState === "restarting";
  const restartLanguageServiceTitle = languageServiceProvider
    ? `重启当前 ${languageServiceProviderLabel(languageServiceProvider)} 语言服务`
    : "重启当前语言服务";

  return (
    <footer
      data-testid="desktop-workbench-statusbar"
      className="desktop-workbench-statusbar flex items-center justify-between gap-1.5 border-t border-[var(--workbench-hairline)] bg-[var(--workbench-statusbar-bg)] px-2 py-0.5 text-xs text-[var(--text)]"
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="truncate font-mono">{activeFilePath || "未打开文件"}</span>
        <span>{fileDirty ? "未保存" : "已保存"}</span>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <span>{debugStatus.connectionText}</span>
        {debugStatus.targetText ? <span className="font-mono">{debugStatus.targetText}</span> : null}
        {debugLocation ? <span className="max-w-[16rem] truncate font-mono">{debugLocation}</span> : null}
        <span>{terminalStatus.connectionText}</span>
        <span className="max-w-[24rem] truncate font-mono">{terminalStatus.currentCwd || "未启动"}</span>
        {terminalStatus.nextTerminalCwd ? (
          <span className="max-w-[24rem] truncate font-mono">新终端目录: {terminalStatus.nextTerminalCwd}</span>
        ) : null}
        {branchName ? <span className="font-mono">{branchName}</span> : null}
        {languageService ? (
          <span
            data-testid="workbench-language-service"
            data-language-service-status={languageServiceRestartInProgress
              ? "restarting"
              : languageServiceLoading
              ? "loading"
              : languageServiceStatus?.runtimeState || languageServiceStatus?.status || "unknown"}
            title={languageServiceRestartInProgress
              ? "正在请求重启当前语言服务"
              : languageServiceStatus?.runtimeMessage
              || languageServiceStatus?.error
              || languageServiceStatus?.message
              || languageServiceStatus?.commandSummary
              || undefined}
          >
            {languageService}
          </span>
        ) : null}
        {onRestartLanguageService && languageServiceProvider ? (
          <button
            type="button"
            aria-label="重启当前语言服务"
            title={restartLanguageServiceTitle}
            disabled={languageServiceRestartInProgress}
            onClick={() => {
              void onRestartLanguageService();
            }}
            className="inline-flex h-5 w-5 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5${languageServiceRestartInProgress ? " animate-spin" : ""}`} aria-hidden="true" />
          </button>
        ) : null}
        {languageServiceRestartError ? (
          <span
            role="alert"
            data-testid="workbench-language-service-restart-error"
            className="max-w-[20rem] truncate text-red-600"
            title={languageServiceRestartError}
          >
            重启失败：{languageServiceRestartError}
          </span>
        ) : null}
        <span
          data-workbench-status={chatStatus.processing ? "active" : chatStatus.state}
          data-status-comet={chatStatus.processing ? "true" : "false"}
        >
          {chatLabel(chatStatus)}
        </span>
        <span>{restoreLabel(restoreState)}</span>
        {rightAction ? <span className="flex items-center">{rightAction}</span> : null}
        <span>{viewModeLabel(viewMode)}</span>
      </div>
    </footer>
  );
}
