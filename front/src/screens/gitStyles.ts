import { clsx } from "clsx";

/** Shared compact Git workbench control styles. */
export const gitFocusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)]";

export function gitIconButtonClass(size: "sm" | "md", tone: "default" | "danger" = "default") {
  return clsx(
    "inline-flex shrink-0 items-center justify-center rounded-[var(--radius-control)] text-[var(--muted)] transition-colors",
    "hover:bg-[var(--workbench-hover-bg)] disabled:pointer-events-none disabled:opacity-40",
    size === "md" ? "h-7 w-7" : "h-6 w-6",
    tone === "danger" ? "hover:text-[var(--danger)]" : "hover:text-[var(--text)]",
    gitFocusRing,
  );
}

export const gitIconButtonClassName = gitIconButtonClass("sm");

export const gitDangerIconButtonClassName = gitIconButtonClass("sm", "danger");

export const gitToolbarIconButtonClassName = clsx(gitIconButtonClass("md"), "relative");

export const gitButtonClassName = clsx(
  "inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2 text-xs font-medium text-[var(--text)] transition-colors",
  "hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] disabled:pointer-events-none disabled:opacity-50",
  gitFocusRing,
);

export const gitSquareButtonClassName = clsx(
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] text-[var(--muted)] transition-colors",
  "hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:pointer-events-none disabled:opacity-50",
  gitFocusRing,
);

export const gitDangerSquareButtonClassName = clsx(
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] text-[var(--muted)] transition-colors",
  "hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--danger)] disabled:pointer-events-none disabled:opacity-50",
  gitFocusRing,
);

export const gitPrimaryButtonClassName = clsx(
  "tcb-solid-accent inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-transparent px-2.5 text-xs font-medium transition-opacity",
  "hover:opacity-90 disabled:pointer-events-none disabled:opacity-50",
  gitFocusRing,
);

export const gitInputBase = clsx(
  "h-7 min-w-0 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2 text-xs text-[var(--text)] outline-none transition-colors",
  "placeholder:text-[var(--muted)] focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60",
);

export const gitSelectCompactClassName = clsx(gitInputBase, "w-auto");

export const gitInputClassName = clsx(gitInputBase, "w-full");

export function gitSegmentClass(active: boolean) {
  return clsx(
    "inline-flex h-5 items-center rounded-[calc(var(--radius-control)-2px)] px-1.5 text-[11px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
    gitFocusRing,
    active
      ? "bg-[var(--workbench-panel-elevated-bg)] text-[var(--accent)] shadow-[var(--shadow-surface)]"
      : "text-[var(--muted)] hover:text-[var(--text)]",
  );
}

export const gitSegmentGroupClassName = "inline-flex items-center gap-0.5 rounded-[var(--radius-control)] bg-[var(--workbench-active-bg)] p-0.5";

export const gitEmptyStateClassName = "px-3 py-1.5 text-xs text-[var(--muted)]";
