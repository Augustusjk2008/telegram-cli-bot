import { clsx } from "clsx";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import {
  Bot,
  ChevronRight,
  ChevronsUpDown,
  FolderGit2,
  GitBranch,
  LogOut,
  MonitorSmartphone,
  Search,
  type LucideIcon,
} from "lucide-react";
import type { ViewMode } from "../app/layoutMode";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import { AppLogo } from "../components/AppLogo";
import { WORKBENCH_PANE_ICONS } from "./workbenchPaneIcons";
import type { } from "./workbenchTypes";

type LayoutControlId = "sidebar" | "editor" | "terminal" | "chat";

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
  clearUnreadAction?: ReactNode;
  announcementAction?: ReactNode;
  workspaceAction?: ReactNode;
  /** Rendered right after the layout toggle group (the desktop layout menu). */
  layoutAction?: ReactNode;
  sidebarVisible: boolean;
  editorVisible: boolean;
  terminalVisible: boolean;
  chatVisible: boolean;
  availableLayoutControls?: LayoutControlId[];
  onToggleSidebar: () => void;
  onToggleEditor: () => void;
  onToggleTerminal: () => void;
  onToggleChat: () => void;
  onViewModeChange: (viewMode: ViewMode) => void;
  onOpenBotSwitcher: (anchorRect?: DOMRect) => void;
  onOpenCommandPalette?: () => void;
  onLogout: () => void;
};

export function WorkbenchHeader({
  currentBot,
  workspaceName,
  viewMode,
  branchName = "",
  hasUnreadOtherBots = false,
  clearUnreadAction,
  announcementAction,
  workspaceAction,
  layoutAction,
  sidebarVisible,
  editorVisible,
  terminalVisible,
  chatVisible,
  availableLayoutControls,
  onToggleSidebar,
  onToggleEditor,
  onToggleTerminal,
  onToggleChat,
  onViewModeChange,
  onOpenBotSwitcher,
  onOpenCommandPalette,
  onLogout,
}: Props) {
  const reduceMotion = useReducedMotion();
  const botLabelMotion = resolveMotionProps(premiumMotion.statusSettle, reduceMotion);
  // Panes can sit anywhere in the layout presets, so the toggles name content instead of positions.
  const layoutControls: Array<{
    id: LayoutControlId;
    visible: boolean;
    Icon: LucideIcon;
    label: string;
    onToggle: () => void;
  }> = [
    {
      id: "sidebar" as const,
      visible: sidebarVisible,
      Icon: WORKBENCH_PANE_ICONS.sidebar,
      label: sidebarVisible ? "隐藏侧边栏" : "显示侧边栏",
      onToggle: onToggleSidebar,
    },
    {
      id: "editor" as const,
      visible: editorVisible,
      Icon: WORKBENCH_PANE_ICONS.editor,
      label: editorVisible ? "隐藏编辑/预览区" : "显示编辑/预览区",
      onToggle: onToggleEditor,
    },
    {
      id: "terminal" as const,
      visible: terminalVisible,
      Icon: WORKBENCH_PANE_ICONS.terminal,
      label: terminalVisible ? "隐藏终端" : "显示终端",
      onToggle: onToggleTerminal,
    },
    {
      id: "chat" as const,
      visible: chatVisible,
      Icon: WORKBENCH_PANE_ICONS.chat,
      label: chatVisible ? "隐藏聊天" : "显示聊天",
      onToggle: onToggleChat,
    },
  ].filter((item) => !availableLayoutControls || availableLayoutControls.includes(item.id));

  return (
    <header
      data-testid="desktop-workbench-titlebar"
      className="workbench-topbar relative z-20 flex min-h-9 items-center justify-between gap-2 px-2 py-1"
    >
      <div className="workbench-topbar-context flex min-w-0 flex-1 items-center gap-2">
        <span className="workbench-topbar-logo flex h-7 w-7 shrink-0 items-center justify-center">
          <AppLogo size={24} decorative />
        </span>
        <button
          type="button"
          aria-label={`切换 Bot: ${currentBot}`}
          onClick={(event) => onOpenBotSwitcher(event.currentTarget.getBoundingClientRect())}
          className="workbench-bot-switch relative inline-flex h-7 max-w-[15rem] items-center gap-1.5 text-xs font-semibold text-[var(--text)] transition-[border-color,box-shadow,background-color]"
        >
          <span className="workbench-bot-avatar" aria-hidden="true">
            <Bot className="h-3.5 w-3.5" />
          </span>
          {hasUnreadOtherBots ? (
            <span
              data-testid="bot-switcher-unread-indicator"
              data-unread-bump={hasUnreadOtherBots ? "true" : "false"}
              aria-hidden="true"
              className="pointer-events-none absolute left-5 top-1 h-2.5 w-2.5 rounded-full bg-[var(--notification-unread)] ring-2 ring-[var(--surface-strong)]"
            />
          ) : null}
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={currentBot}
              className="inline-block min-w-0 truncate text-[13px]"
              {...botLabelMotion}
            >
              {currentBot}
            </motion.span>
          </AnimatePresence>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" aria-hidden="true" />
        </button>
        <nav aria-label="工作区位置" className="workbench-breadcrumb min-w-0">
          <ChevronRight className="workbench-breadcrumb-separator h-3.5 w-3.5" aria-hidden="true" />
          {workspaceAction || <span className="workbench-status-chip min-w-0 max-w-[22rem]">
            <FolderGit2 className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
            <span className="truncate">{workspaceName}</span>
          </span>}
          {branchName ? (
            <>
              <ChevronRight className="workbench-breadcrumb-separator h-3.5 w-3.5" aria-hidden="true" />
              <span className="workbench-status-chip max-w-[14rem] font-mono text-[12px]">
                <GitBranch className="h-3.5 w-3.5 shrink-0 text-[var(--accent-strong)]" />
                <span className="truncate">{branchName}</span>
              </span>
            </>
          ) : null}
        </nav>
      </div>
      {onOpenCommandPalette ? (
        <button
          type="button"
          aria-label="快速打开文件"
          onClick={onOpenCommandPalette}
          className="workbench-command-trigger hidden lg:inline-flex"
        >
          <Search className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate text-left">搜索文件、跳转代码…</span>
          <kbd className="orbit-kbd">Ctrl P</kbd>
        </button>
      ) : null}
      <div className="flex min-w-fit flex-1 items-center justify-end gap-1.5">
        {clearUnreadAction}
        {announcementAction ? (
          <div className="flex items-center">{announcementAction}</div>
        ) : null}
        {layoutControls.length > 0 ? (
          <div
            aria-label="布局开关"
            className="workbench-segmented inline-flex"
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
                    : "text-[var(--muted)] hover:text-[var(--text)]",
                )}
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
        ) : null}
        {layoutAction}
        <div aria-label="视图模式" className="workbench-segmented inline-flex">
          <span className="hidden h-7 items-center px-1.5 text-[var(--muted)] xl:inline-flex" aria-hidden="true">
            <MonitorSmartphone className="h-3.5 w-3.5" />
          </span>
          {VIEW_MODE_OPTIONS.map(({ value: nextMode, label, shortLabel }) => (
            <button
              key={nextMode}
              type="button"
              aria-label={label}
              title={label}
              aria-pressed={viewMode === nextMode}
              onClick={() => onViewModeChange(nextMode)}
              className={clsx(
                "h-7 px-2 text-xs font-medium transition-colors",
                viewMode === nextMode
                  ? "tcb-selected-accent"
                  : "text-[var(--muted)] hover:text-[var(--text)]",
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
          className="workbench-logout inline-flex h-8 w-8 items-center justify-center text-[var(--muted)] transition-colors hover:bg-[var(--fill-hover)] hover:text-[var(--text)]"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
