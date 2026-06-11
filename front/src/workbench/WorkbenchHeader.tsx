import { clsx } from "clsx";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import {
  Bot,
  FolderGit2,
  GitBranch,
  LogOut,
  MonitorSmartphone,
  PanelBottom,
  PanelBottomDashed,
  PanelLeft,
  PanelLeftDashed,
  PanelRight,
  PanelRightDashed,
} from "lucide-react";
import type { ViewMode } from "../app/layoutMode";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import { AppLogo } from "../components/AppLogo";
import type { WorkbenchProductMode } from "./workbenchTypes";

type LayoutControlId = "sidebar" | "terminal" | "chat";

const VIEW_MODE_OPTIONS: Array<{ value: ViewMode; label: string; shortLabel: string }> = [
  { value: "auto", label: "自动", shortLabel: "Auto" },
  { value: "mobile", label: "竖屏版", shortLabel: "竖" },
  { value: "desktop", label: "横屏版", shortLabel: "横" },
];

type Props = {
  currentBot: string;
  workspaceName: string;
  viewMode: ViewMode;
  branchName?: string;
  hasUnreadOtherBots?: boolean;
  announcementAction?: ReactNode;
  sidebarVisible: boolean;
  terminalVisible: boolean;
  chatVisible: boolean;
  availableLayoutControls?: LayoutControlId[];
  productMode?: WorkbenchProductMode;
  soloAvailable?: boolean;
  onProductModeChange?: (mode: WorkbenchProductMode) => void;
  onToggleSidebar: () => void;
  onToggleTerminal: () => void;
  onToggleChat: () => void;
  onViewModeChange: (viewMode: ViewMode) => void;
  onOpenBotSwitcher: (anchorRect?: DOMRect) => void;
  onLogout: () => void;
};

export function WorkbenchHeader({
  currentBot,
  workspaceName,
  viewMode,
  branchName = "",
  hasUnreadOtherBots = false,
  announcementAction,
  sidebarVisible,
  terminalVisible,
  chatVisible,
  availableLayoutControls,
  productMode,
  soloAvailable = false,
  onProductModeChange,
  onToggleSidebar,
  onToggleTerminal,
  onToggleChat,
  onViewModeChange,
  onOpenBotSwitcher,
  onLogout,
}: Props) {
  const reduceMotion = useReducedMotion();
  const botLabelMotion = resolveMotionProps(premiumMotion.statusSettle, reduceMotion);
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
      className="workbench-topbar flex min-h-10 items-center justify-between gap-3 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2.5 py-1.5"
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="workbench-topbar-logo flex h-7 w-7 shrink-0 items-center justify-center border border-[var(--border)] bg-[var(--surface-glass)]">
          <AppLogo size={21} decorative />
        </span>
        {productMode && onProductModeChange ? (
          <div
            aria-label="产品模式"
            className="workbench-segmented inline-flex border border-[var(--border)] bg-[var(--surface-glass)] p-0.5"
            role="group"
          >
            <button
              type="button"
              aria-label="构建模式"
              aria-pressed={productMode === "build"}
              onClick={() => onProductModeChange("build")}
              className={clsx(
                "h-7 px-2 text-xs font-medium transition-colors",
                productMode === "build"
                  ? "tcb-selected-accent"
                  : "text-[var(--text)] hover:bg-[var(--surface-strong)]",
              )}
            >
              构建
            </button>
            <button
              type="button"
              aria-label="Solo 模式"
              aria-pressed={productMode === "solo"}
              disabled={!soloAvailable}
              onClick={() => onProductModeChange("solo")}
              className={clsx(
                "h-7 px-2 text-xs font-medium transition-colors disabled:opacity-50",
                productMode === "solo"
                  ? "tcb-selected-accent"
                  : "text-[var(--text)] hover:bg-[var(--surface-strong)]",
              )}
            >
              Solo
            </button>
          </div>
        ) : null}
        <button
          type="button"
          aria-label={`切换 Bot: ${currentBot}`}
          onClick={(event) => onOpenBotSwitcher(event.currentTarget.getBoundingClientRect())}
          className={clsx(
            "workbench-bot-switch relative inline-flex h-7 max-w-[13rem] items-center gap-1.5 border border-[var(--border)] bg-[var(--surface-glass)] px-2 text-xs font-semibold text-[var(--text)] transition-colors hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]",
            hasUnreadOtherBots ? "pr-4.5" : "",
          )}
        >
          <Bot className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
          {hasUnreadOtherBots ? (
            <span
              data-testid="bot-switcher-unread-indicator"
              data-unread-bump={hasUnreadOtherBots ? "true" : "false"}
              aria-hidden="true"
              className="pointer-events-none absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-[var(--surface-strong)]"
            />
          ) : null}
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={currentBot}
              className="inline-block min-w-0 truncate"
              {...botLabelMotion}
            >
              {currentBot}
            </motion.span>
          </AnimatePresence>
        </button>
        <span className="workbench-status-chip min-w-0 max-w-[22rem] text-[var(--muted)]">
          <FolderGit2 className="h-3.5 w-3.5 shrink-0 text-[var(--accent-strong)]" />
          <span className="truncate">{workspaceName}</span>
        </span>
        {branchName ? (
          <span className="workbench-status-chip max-w-[14rem] font-mono text-[var(--muted)]">
            <GitBranch className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
            <span className="truncate">{branchName}</span>
          </span>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {announcementAction ? (
          <div className="flex items-center">{announcementAction}</div>
        ) : null}
        {layoutControls.length > 0 ? (
          <div
            aria-label="布局开关"
            className="workbench-segmented inline-flex border border-[var(--border)] bg-[var(--surface-glass)] p-0.5"
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
                  "inline-flex h-7 w-7 items-center justify-center transition-colors",
                  visible
                    ? "tcb-selected-accent"
                    : "text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]",
                )}
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
        ) : null}
        <div aria-label="视图模式" className="workbench-segmented inline-flex border border-[var(--border)] bg-[var(--surface-glass)] p-0.5">
          <span className="hidden h-7 items-center px-1.5 text-[var(--muted)] sm:inline-flex" aria-hidden="true">
            <MonitorSmartphone className="h-3.5 w-3.5" />
          </span>
          {VIEW_MODE_OPTIONS.map(({ value: nextMode, label, shortLabel }) => (
            <button
              key={nextMode}
              type="button"
              aria-label={label}
              title={label}
              onClick={() => onViewModeChange(nextMode)}
              className={clsx(
                "h-7 px-2 text-xs font-medium transition-colors",
                viewMode === nextMode
                  ? "tcb-selected-accent"
                  : "text-[var(--text)] hover:bg-[var(--surface-strong)]",
              )}
            >
              {shortLabel}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-label="退出登录"
          title="退出登录"
          onClick={onLogout}
          className="inline-flex h-8 w-8 items-center justify-center border border-[var(--border)] bg-[var(--surface-glass)] text-[var(--muted)] transition-colors hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
