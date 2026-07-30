import { clsx } from "clsx";
import type { ComponentPropsWithoutRef } from "react";

type Props = ComponentPropsWithoutRef<"section"> & {
  elevated?: boolean;
  padded?: boolean;
};

export function SurfacePanel({
  elevated = false,
  padded = false,
  className,
  children,
  ...props
}: Props) {
  return (
    <section
      {...props}
      className={clsx(
        "min-w-0 overflow-hidden rounded-[var(--radius-panel)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-surface)]",
        elevated ? "bg-[var(--workbench-panel-elevated-bg)]" : "",
        padded ? "p-3" : "",
        className,
      )}
    >
      {children}
    </section>
  );
}
