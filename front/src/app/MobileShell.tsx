import { useEffect, useRef, useState, type ReactNode } from "react";
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
  const [viewModeMenuOpen, setViewModeMenuOpen] = useState(false);
  const viewModeRootRef = useRef<HTMLDivElement>(null);
  const viewModeTriggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!viewModeMenuOpen) return;
    const closeOnPointerDown = (event: PointerEvent) => {
      if (!viewModeRootRef.current?.contains(event.target as Node)) setViewModeMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setViewModeMenuOpen(false);
        viewModeTriggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnPointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [viewModeMenuOpen]);
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
    <div data-layout="mobile" className="relative flex h-[100dvh] w-full min-w-0 flex-col overflow-hidden bg-[var(--workbench-shell-bg)] text-[var(--text)]">
      {!hideOuterChrome ? (
        <header className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2">
          <button
            onClick={onOpenBotSwitcher}
            className={clsx(
              "relative flex h-8 min-w-0 max-w-[48vw] items-center gap-1.5 rounded-md border border-[var(--border)] bg-transparent px-2 text-sm font-semibold transition-colors hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]",
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
          <div ref={viewModeRootRef} className="relative flex min-w-0 items-center gap-1">
            {announcementAction}
            <button
              ref={viewModeTriggerRef}
              type="button"
              aria-label="视图模式"
              aria-haspopup="menu"
              aria-expanded={viewModeMenuOpen}
              title="视图模式"
              onClick={() => setViewModeMenuOpen((value) => !value)}
              className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-[var(--border)] px-1.5 text-[11px] font-medium text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
            >
              <MonitorSmartphone className="h-3.5 w-3.5 text-[var(--muted)]" />
              {VIEW_MODE_OPTIONS.find((option) => option.value === viewMode)?.shortLabel}
            </button>
            {viewModeMenuOpen ? (
              <div role="menu" aria-label="视图模式" className="absolute right-0 top-full z-40 mt-1 w-24 rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] p-1 shadow-[var(--shadow-card)]">
                {VIEW_MODE_OPTIONS.map(({ value: nextMode, label }) => (
                  <button
                    key={nextMode}
                    type="button"
                    role="menuitemradio"
                    aria-checked={viewMode === nextMode}
                    onClick={() => {
                      onViewModeChange(nextMode);
                      setViewModeMenuOpen(false);
                      viewModeTriggerRef.current?.focus();
                    }}
                    className={clsx(
                      "flex h-7 w-full items-center rounded px-2 text-left text-xs",
                      viewMode === nextMode ? "tcb-selected-accent" : "text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </header>
      ) : null}

      <div className="flex-1 overflow-hidden relative">
        {activeScreen}
      </div>

      {!hideOuterChrome ? (
        <nav className="flex h-[calc(2.75rem+env(safe-area-inset-bottom))] shrink-0 items-center justify-around gap-0.5 border-t border-[var(--workbench-hairline)] bg-[var(--workbench-statusbar-bg)] px-1 pb-[env(safe-area-inset-bottom)]">
          {navItems.map(({ tab, label, Icon }) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              aria-current={currentTab === tab ? "page" : undefined}
              className={clsx(
                "flex h-full min-w-0 flex-1 flex-col items-center justify-center rounded-md border border-transparent px-1 transition-colors",
                currentTab === tab
                  ? "tcb-selected-accent"
                  : "text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]",
              )}
            >
              <Icon className="mb-0 h-4 w-4 shrink-0" />
              <span className="max-w-full truncate text-[10px] font-medium leading-3">{label}</span>
            </button>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
