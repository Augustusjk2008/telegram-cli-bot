import { Settings } from "lucide-react";
import type { TerminalAction, TerminalRuntimePlatform } from "../services/types";
import { isTerminalActionVisible, resolveTerminalActionCommand } from "./terminalActionPlatform";
import { getTerminalActionIcon } from "./terminalActionIcons";

type Props = {
  actions: TerminalAction[];
  runtimePlatform: TerminalRuntimePlatform;
  canEdit: boolean;
  disabled?: boolean;
  runningActionId: string;
  onRunAction: (action: TerminalAction) => void;
  onOpenConfig: () => void;
};

export function TerminalActionsBar({
  actions,
  runtimePlatform,
  canEdit,
  disabled = false,
  runningActionId,
  onRunAction,
  onOpenConfig,
}: Props) {
  const visibleActions = actions.filter((action) => isTerminalActionVisible(action, runtimePlatform));
  if (visibleActions.length === 0 && !canEdit) {
    return null;
  }

  return (
    <div className="flex min-w-0 items-center gap-2 overflow-x-auto">
      {visibleActions.map((action) => {
        const Icon = getTerminalActionIcon(action.icon);
        const running = runningActionId === action.id;
        const command = resolveTerminalActionCommand(action, runtimePlatform);
        return (
          <button
            key={action.id}
            type="button"
            aria-label={action.label}
            title={command}
            onClick={() => onRunAction(action)}
            disabled={disabled || running}
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
          disabled={disabled}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
        >
          <Settings className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}
