import type { ReactNode } from "react";

type Props = {
  testId: string;
  title: string;
  collapsed: boolean;
  collapseLabel: string;
  expandLabel: string;
  onToggleCollapsed: () => void;
  children: ReactNode;
};

export function PaneChrome({
  testId,
  title,
  collapsed,
  collapseLabel,
  expandLabel,
  onToggleCollapsed,
  children,
}: Props) {
  return (
    <section
      data-testid={testId}
      data-collapsed={collapsed ? "true" : "false"}
      className="flex min-h-0 min-w-0 flex-col overflow-hidden border border-[var(--border)] bg-[var(--surface)]"
    >
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2">
        <h2 className="truncate text-sm font-semibold text-[var(--text)]">{title}</h2>
        <button
          type="button"
          aria-label={collapsed ? expandLabel : collapseLabel}
          onClick={onToggleCollapsed}
          className="rounded-lg border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--surface)]"
        >
          {collapsed ? "展开" : "折叠"}
        </button>
      </header>
      <div className={collapsed ? "hidden min-h-0 flex-1" : "flex min-h-0 flex-1"}>{children}</div>
    </section>
  );
}
