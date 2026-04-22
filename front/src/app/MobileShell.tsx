import type { ReactNode } from "react";
import {
  Bug,
  Folder,
  GitBranch,
  Menu,
  MessageSquare,
  Settings,
  SquareTerminal,
  type LucideIcon,
} from "lucide-react";
import { clsx } from "clsx";
import type { ViewMode } from "./layoutMode";
import type { SessionState } from "../services/types";
import { isGuest } from "../utils/capabilities";

export type AppTab = "chat" | "files" | "debug" | "terminal" | "git" | "settings";

type Props = {
  session: SessionState | null;
  currentBot: string;
  currentTab: AppTab;
  hideOuterChrome: boolean;
  activeScreen: ReactNode;
  viewMode: ViewMode;
  hasUnreadOtherBots?: boolean;
  onOpenBotSwitcher: () => void;
  onViewModeChange: (viewMode: ViewMode) => void;
  onTabChange: (tab: AppTab) => void;
};

export function MobileShell({
  session,
  currentBot,
  currentTab,
  hideOuterChrome,
  activeScreen,
  viewMode,
  hasUnreadOtherBots = false,
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
    { tab: "settings", label: "设置", Icon: Settings },
  ];
  const navItems = isGuest(session)
    ? fullNavItems.filter((item) => item.tab === "chat" || item.tab === "files")
    : fullNavItems;

  return (
    <div className="flex min-w-0 flex-col h-[100dvh] w-full bg-[var(--bg)] shadow-xl overflow-hidden relative">
      {!hideOuterChrome ? (
        <header className="flex items-center justify-between p-3 bg-[var(--surface-strong)] border-b border-[var(--border)] shrink-0">
          <button
            onClick={onOpenBotSwitcher}
            className={clsx(
              "relative flex items-center gap-2 rounded-lg px-3 py-1.5 transition-colors hover:bg-[var(--border)]",
              hasUnreadOtherBots ? "pr-5" : "",
            )}
          >
            {hasUnreadOtherBots ? (
              <span
                data-testid="bot-switcher-unread-indicator"
                aria-hidden="true"
                className="pointer-events-none absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-[var(--surface-strong)]"
              />
            ) : null}
            <Menu className="w-5 h-5" />
            <span className="font-semibold">{currentBot}</span>
          </button>
          <div className="inline-flex rounded-xl border border-[var(--border)] bg-[var(--surface)] p-1">
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
                  "rounded-lg px-2 py-1 text-xs transition-colors",
                  viewMode === nextMode
                    ? "bg-[var(--accent)] text-white"
                    : "text-[var(--text)] hover:bg-[var(--surface-strong)]",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </header>
      ) : null}

      <div className="flex-1 overflow-hidden relative">
        {activeScreen}
      </div>

      {!hideOuterChrome ? (
        <nav className="flex items-center justify-around gap-1 p-2 bg-[var(--surface-strong)] border-t border-[var(--border)] shrink-0 pb-safe">
          {navItems.map(({ tab, label, Icon }) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              className={clsx(
                "flex min-w-0 flex-1 flex-col items-center rounded-xl p-1.5",
                currentTab === tab ? "text-[var(--accent)]" : "text-[var(--muted)]",
              )}
            >
              <Icon className="mb-1 h-5 w-5" />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
