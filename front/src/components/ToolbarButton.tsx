import { clsx } from "clsx";
import type { ButtonHTMLAttributes } from "react";

type ToolbarButtonVariant = "plain" | "primary" | "danger" | "ghost";
type ToolbarButtonSize = "sm" | "md" | "icon";

export function toolbarButtonClass(
  variant: ToolbarButtonVariant = "plain",
  size: ToolbarButtonSize = "sm",
  extra = "",
) {
  return clsx(
    "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:pointer-events-none disabled:opacity-55",
    size === "icon" ? "h-8 w-8 px-0" : size === "md" ? "h-9 px-3" : "h-8 px-2.5",
    variant === "primary"
      ? "border border-transparent bg-[var(--accent)] text-[var(--accent-foreground)] hover:opacity-90"
      : variant === "danger"
        ? "border border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
        : variant === "ghost"
          ? "border border-transparent text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"
          : "border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] text-[var(--text)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]",
    extra,
  );
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ToolbarButtonVariant;
  size?: ToolbarButtonSize;
};

export function ToolbarButton({
  variant = "plain",
  size = "sm",
  className,
  children,
  ...props
}: Props) {
  return (
    <button {...props} className={toolbarButtonClass(variant, size, className)}>
      {children}
    </button>
  );
}
