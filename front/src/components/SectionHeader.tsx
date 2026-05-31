import { clsx } from "clsx";
import type { ReactNode } from "react";

type Props = {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

export function SectionHeader({ title, description, icon, actions, className }: Props) {
  return (
    <div
      className={clsx(
        "flex min-w-0 items-center justify-between gap-3 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          {icon ? <span className="shrink-0 text-[var(--accent)]">{icon}</span> : null}
          <h2 className="min-w-0 truncate text-sm font-semibold text-[var(--text)]">{title}</h2>
        </div>
        {description ? <p className="mt-1 truncate text-xs text-[var(--muted)]">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}
