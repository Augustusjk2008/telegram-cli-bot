import type { ReactNode } from "react";
import {
  Bug,
  Folder,
  GitBranch,
  Menu,
  MessageSquare,
  MonitorSmartphone,
  Puzzle,
  Settings,
  SquareTerminal,
  type LucideIcon,
} from "lucide-react";
import { clsx } from "clsx";
import type { ViewMode } from "./layoutMode";
import type { SessionState } from "../services/types";
import { isGuest } from "../utils/capabilities";
import { AppLogo } from "../components/AppLogo";

export type AppTab = "chat" | "files" | "debug" | "terminal" | "git" | "plugins" | "settings";

const VIEW_MODE_OPTIONS: Array<{ value: ViewMode; label: string; shortLabel: string }> = [
  { value: "auto", label: "自动", shortLabel: "Auto" },
  { value: "mobile", label: "竖屏版", shortLabel: "竖" },
  { value: "desktop", label: "横屏版", shortLabel: "横" },
];

type Props = {
  session: SessionState | null;
  currentBot: string;
  currentTab: AppTab;
  allowedTabs?: AppTab[];
  hideOuterChrome: boolean;
  activeScreen: ReactNode;
  viewMode: ViewMode;
  hasUnreadOtherBots?: boolean;
  announcementAction?: ReactNode;
  onOpenBotSwitcher: () => void;
  onViewModeChange: (viewMode: ViewMode) => void;
  onTabChange: (tab: AppTab) => void;
};

export function MobileShell({
  session,
  currentBot,
  currentTab,
  allowedTabs,
  hideOuterChrome,
  activeScreen,
  viewMode,
  hasUnreadOtherBots = false,
  announcementAction,
  onOpenBotSwitcher,
  onViewModeChange,
  onTabChange,
}: Props) {
  const fullNavItems: Array<{ tab: AppTab; label: string; Icon: LucideIcon }> = [
    { tab: "chat", label: "聊天", Icon: MessageSquare },
    { tab: "files", label: "文件", Icon: Folder },
    { tab: "debug", label: "调试", Icon: Bug },
    { tab: "terminal", label: "终端", Icon: SquareTerminal },
    { tab: "git", label: "Git", Icon: GitBranch },
    { tab: "plugins", label: "插件", Icon: Puzzle },
    { tab: "settings", label: "设置", Icon: Settings },
  ];
  const navItems = isGuest(session)
    ? fullNavItems.filter((item) => item.tab === "chat" || item.tab === "files")
    : fullNavItems.filter((item) => (
        allowedTabs
          ? allowedTabs.includes(item.tab)
          : item.tab !== "plugins" || session?.capabilities.includes("view_plugins")
      ));

  return (
    <div className="relative flex h-[100dvh] w-full min-w-0 flex-col overflow-hidden bg-[var(--workbench-shell-bg)] text-[var(--text)] shadow-xl">
      {!hideOuterChrome ? (
        <header className="flex min-h-12 shrink-0 items-center justify-between gap-2 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2.5 py-2">
          <button
            onClick={onOpenBotSwitcher}
            className={clsx(
              "relative flex h-8 min-w-0 max-w-[48vw] items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-glass)] px-2 text-sm font-semibold transition-colors hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]",
              hasUnreadOtherBots ? "pr-5" : "",
            )}
          >
            {hasUnreadOtherBots ? (
              <span
                data-testid="bot-switcher-unread-indicator"
                aria-hidden="true"
                className="pointer-events-none absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-[var(--workbench-titlebar-bg)]"
              />
            ) : null}
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--surface-glass)]">
              <AppLogo size={18} decorative />
            </span>
            <span className="min-w-0 truncate">{currentBot}</span>
            <Menu className="h-4 w-4 shrink-0 text-[var(--muted)]" />
          </button>
          <div className="flex min-w-0 items-center gap-1.5">
            {announcementAction}
            <div
              aria-label="视图模式"
              role="group"
              className="inline-flex h-8 shrink-0 items-center overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface-glass)] p-0.5"
            >
              <span className="hidden h-7 items-center px-1 text-[var(--muted)] min-[380px]:inline-flex" aria-hidden="true">
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
                    "h-7 min-w-8 px-1.5 text-[11px] font-medium transition-colors",
                    viewMode === nextMode
                      ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                      : "text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]",
                  )}
                >
                  {shortLabel}
                </button>
              ))}
            </div>
          </div>
        </header>
      ) : null}

      <div className="flex-1 overflow-hidden relative">
        {activeScreen}
      </div>

      {!hideOuterChrome ? (
        <nav className="flex shrink-0 items-center justify-around gap-1 border-t border-[var(--workbench-hairline)] bg-[var(--workbench-statusbar-bg)] px-1.5 py-1.5 pb-[calc(env(safe-area-inset-bottom)+0.375rem)]">
          {navItems.map(({ tab, label, Icon }) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              aria-current={currentTab === tab ? "page" : undefined}
              className={clsx(
                "flex min-w-0 flex-1 flex-col items-center rounded-md border border-transparent px-1 py-1.5 transition-colors",
                currentTab === tab
                  ? "border-[var(--workbench-hover-border)] bg-[var(--workbench-active-bg)] text-[var(--accent)]"
                  : "text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]",
              )}
            >
              <Icon className="mb-0.5 h-5 w-5 shrink-0" />
              <span className="max-w-full truncate text-[10px] font-medium leading-4">{label}</span>
            </button>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
