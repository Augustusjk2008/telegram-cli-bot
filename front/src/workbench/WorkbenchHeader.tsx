import { clsx } from "clsx";
import type { ViewMode } from "../app/layoutMode";

type Props = {
  currentBot: string;
  workspaceName: string;
  viewMode: ViewMode;
  onViewModeChange: (viewMode: ViewMode) => void;
  onOpenBotSwitcher: () => void;
};

export function WorkbenchHeader({ currentBot, workspaceName, viewMode, onViewModeChange, onOpenBotSwitcher }: Props) {
  return (
    <header
      data-testid="desktop-workbench-titlebar"
      className="flex items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--surface-strong)] px-4 py-2"
    >
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onOpenBotSwitcher}
          className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium hover:bg-[var(--surface)]"
        >
          {currentBot}
        </button>
        <span className="truncate text-xs text-[var(--muted)]">{workspaceName}</span>
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
