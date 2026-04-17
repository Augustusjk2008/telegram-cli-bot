import { clsx } from "clsx";
import type { ViewMode } from "../app/layoutMode";

type Props = {
  currentBot: string;
  viewMode: ViewMode;
  onViewModeChange: (viewMode: ViewMode) => void;
  onOpenBotSwitcher: () => void;
};

export function WorkbenchHeader({ currentBot, viewMode, onViewModeChange, onOpenBotSwitcher }: Props) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--surface-strong)] px-4 py-3">
      <button
        type="button"
        onClick={onOpenBotSwitcher}
        className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm font-medium hover:bg-[var(--surface)]"
      >
        {currentBot}
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
              "rounded-lg px-3 py-1.5 text-sm transition-colors",
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
