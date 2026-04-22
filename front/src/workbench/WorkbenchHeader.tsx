import { clsx } from "clsx";
import {
  PanelBottom,
  PanelBottomDashed,
  PanelLeft,
  PanelLeftDashed,
  PanelRight,
  PanelRightDashed,
} from "lucide-react";
import type { ViewMode } from "../app/layoutMode";

type LayoutControlId = "sidebar" | "terminal" | "chat";

type Props = {
  currentBot: string;
  workspaceName: string;
  viewMode: ViewMode;
  branchName?: string;
  hasUnreadOtherBots?: boolean;
  sidebarVisible: boolean;
  terminalVisible: boolean;
  chatVisible: boolean;
  availableLayoutControls?: LayoutControlId[];
  onToggleSidebar: () => void;
  onToggleTerminal: () => void;
  onToggleChat: () => void;
  onViewModeChange: (viewMode: ViewMode) => void;
  onOpenBotSwitcher: () => void;
};

export function WorkbenchHeader({
  currentBot,
  workspaceName,
  viewMode,
  branchName = "",
  hasUnreadOtherBots = false,
  sidebarVisible,
  terminalVisible,
  chatVisible,
  availableLayoutControls,
  onToggleSidebar,
  onToggleTerminal,
  onToggleChat,
  onViewModeChange,
  onOpenBotSwitcher,
}: Props) {
  const layoutControls: Array<{
    id: LayoutControlId;
    visible: boolean;
    Icon: typeof PanelLeft;
    label: string;
    onToggle: () => void;
  }> = [
    {
      id: "sidebar" as const,
      visible: sidebarVisible,
      Icon: sidebarVisible ? PanelLeft : PanelLeftDashed,
      label: sidebarVisible ? "隐藏左侧栏" : "显示左侧栏",
      onToggle: onToggleSidebar,
    },
    {
      id: "terminal" as const,
      visible: terminalVisible,
      Icon: terminalVisible ? PanelBottom : PanelBottomDashed,
      label: terminalVisible ? "隐藏底部终端" : "显示底部终端",
      onToggle: onToggleTerminal,
    },
    {
      id: "chat" as const,
      visible: chatVisible,
      Icon: chatVisible ? PanelRight : PanelRightDashed,
      label: chatVisible ? "隐藏右侧聊天" : "显示右侧聊天",
      onToggle: onToggleChat,
    },
  ].filter((item) => !availableLayoutControls || availableLayoutControls.includes(item.id));

  return (
    <header
      data-testid="desktop-workbench-titlebar"
      className="flex items-center justify-between gap-3 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 py-1.5"
    >
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={onOpenBotSwitcher}
          className={clsx(
            "relative rounded-lg border border-[var(--border)] px-2.5 py-1 text-sm font-medium hover:bg-[var(--surface)]",
            hasUnreadOtherBots ? "pr-4.5" : "",
          )}
        >
          {hasUnreadOtherBots ? (
            <span
              data-testid="bot-switcher-unread-indicator"
              aria-hidden="true"
              className="pointer-events-none absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-[var(--surface-strong)]"
            />
          ) : null}
          {currentBot}
        </button>
        <span className="truncate text-xs text-[var(--muted)]">{workspaceName}</span>
        {branchName ? (
          <span className="rounded-md border border-[var(--border)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--muted)]">
            {branchName}
          </span>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {layoutControls.length > 0 ? (
          <div
            aria-label="布局开关"
            className="inline-flex rounded-lg border border-[var(--border)] bg-[var(--surface)] p-0.5"
            role="group"
          >
            {layoutControls.map(({ id, visible, Icon, label, onToggle }) => (
              <button
                key={id}
                type="button"
                aria-label={label}
                aria-pressed={visible}
                title={label}
                onClick={onToggle}
                className={clsx(
                  "inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors",
                  visible
                    ? "bg-[var(--surface-strong)] text-[var(--text)]"
                    : "text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]",
                )}
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
        ) : null}
        <div className="inline-flex rounded-lg border border-[var(--border)] bg-[var(--surface)] p-0.5">
          {([
            ["auto", "自动"],
            ["mobile", "手机版"],
            ["desktop", "桌面版"],
          ] as const).map(([nextMode, label]) => (
            <button
              key={nextMode}
              type="button"
              onClick={() => onViewModeChange(nextMode)}
              className={clsx(
                "rounded-md px-2.5 py-0.5 text-xs transition-colors",
                viewMode === nextMode
                  ? "bg-[var(--accent)] text-white"
                  : "text-[var(--text)] hover:bg-[var(--surface-strong)]",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
