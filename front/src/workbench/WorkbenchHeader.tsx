import { clsx } from "clsx";
import type { ViewMode } from "../app/layoutMode";

type Props = {
  currentBot: string;
  workspaceName: string;
  viewMode: ViewMode;
  branchName?: string;
  hasUnreadOtherBots?: boolean;
  onViewModeChange: (viewMode: ViewMode) => void;
  onOpenBotSwitcher: () => void;
};

export function WorkbenchHeader({
  currentBot,
  workspaceName,
  viewMode,
  branchName = "",
  hasUnreadOtherBots = false,
  onViewModeChange,
  onOpenBotSwitcher,
}: Props) {
  return (
    <header
      data-testid="desktop-workbench-titlebar"
      className="flex items-center justify-between gap-4 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-4 py-2"
    >
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onOpenBotSwitcher}
          className={clsx(
            "relative rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium hover:bg-[var(--surface)]",
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
          {currentBot}
        </button>
        <span className="truncate text-xs text-[var(--muted)]">{workspaceName}</span>
        {branchName ? (
          <span className="rounded-md border border-[var(--border)] px-2 py-1 font-mono text-[11px] text-[var(--muted)]">
            {branchName}
          </span>
        ) : null}
      </div>
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
              "rounded-md px-3 py-1 text-xs transition-colors",
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
  );
}
