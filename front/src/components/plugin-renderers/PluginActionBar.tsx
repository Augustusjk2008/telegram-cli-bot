import { clsx } from "clsx";
import type { PluginAction } from "../../services/types";

type Props = {
  actions?: PluginAction[];
  onRunAction?: (action: PluginAction) => void;
};

function variantClass(variant: PluginAction["variant"]) {
  if (variant === "primary") {
    return "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]";
  }
  if (variant === "danger") {
    return "border-red-300 bg-red-50 text-red-700";
  }
  return "border-[var(--border)] text-[var(--text)]";
}

export function PluginActionBar({ actions = [], onRunAction }: Props) {
  if (actions.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-3 py-2">
      {actions.map((action) => (
        <button
          key={action.id}
          type="button"
          disabled={action.disabled || !onRunAction}
          title={action.tooltip || action.label}
          onClick={() => onRunAction?.(action)}
          className={clsx(
            "rounded-lg border px-3 py-1.5 text-sm transition hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-60",
            variantClass(action.variant),
          )}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
