import type { ReactNode } from "react";
import { Folder, GitBranch, Menu, MessageSquare, Settings, SquareTerminal } from "lucide-react";
import { clsx } from "clsx";
import type { ViewMode } from "./layoutMode";

export type AppTab = "chat" | "files" | "terminal" | "git" | "settings";

type Props = {
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
        <nav className="flex items-center justify-around p-2 bg-[var(--surface-strong)] border-t border-[var(--border)] shrink-0 pb-safe">
          {[
            ["chat", "聊天", MessageSquare],
            ["files", "文件", Folder],
            ["terminal", "终端", SquareTerminal],
            ["git", "Git", GitBranch],
            ["settings", "设置", Settings],
          ].map(([tab, label, Icon]) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab as AppTab)}
              className={clsx(
                "flex flex-col items-center p-2 rounded-xl min-w-[64px]",
                currentTab === tab ? "text-[var(--accent)]" : "text-[var(--muted)]",
              )}
            >
              <Icon className="w-6 h-6 mb-1" />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
