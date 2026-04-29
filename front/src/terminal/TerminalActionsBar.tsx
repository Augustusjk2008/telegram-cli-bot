import { Settings } from "lucide-react";
import type { TerminalAction } from "../services/types";
import { getTerminalActionIcon } from "./terminalActionIcons";

type Props = {
  actions: TerminalAction[];
  canEdit: boolean;
  runningActionId: string;
  onRunAction: (action: TerminalAction) => void;
  onOpenConfig: () => void;
};

export function TerminalActionsBar({
  actions,
  canEdit,
  runningActionId,
  onRunAction,
  onOpenConfig,
}: Props) {
  const enabledActions = actions.filter((action) => action.enabled);
  if (enabledActions.length === 0 && !canEdit) {
    return null;
  }

  return (
    <div className="flex min-w-0 items-center gap-2 overflow-x-auto">
      {enabledActions.map((action) => {
        const Icon = getTerminalActionIcon(action.icon);
        const running = runningActionId === action.id;
        return (
          <button
            key={action.id}
            type="button"
            aria-label={action.label}
            title={action.command}
            onClick={() => onRunAction(action)}
            disabled={running}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-[var(--border)] px-2 text-xs font-medium text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="max-w-24 truncate">{running ? "执行中" : action.label}</span>
          </button>
        );
      })}
      {canEdit ? (
        <button
          type="button"
          aria-label="编辑快捷命令"
          title="编辑快捷命令"
          onClick={onOpenConfig}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
        >
          <Settings className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}
