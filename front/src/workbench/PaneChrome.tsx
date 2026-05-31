import type { ReactNode } from "react";
import { ChevronsDownUp, ChevronsUpDown } from "lucide-react";

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
      className="workbench-pane-chrome flex min-h-0 min-w-0 flex-col overflow-hidden border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)]"
    >
      <header className="workbench-pane-header flex h-9 items-center justify-between gap-3 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2.5">
        <h2 className="min-w-0 truncate text-[13px] font-semibold text-[var(--text)]">{title}</h2>
        <button
          type="button"
          aria-label={collapsed ? expandLabel : collapseLabel}
          title={collapsed ? expandLabel : collapseLabel}
          onClick={onToggleCollapsed}
          className="inline-flex h-7 w-7 items-center justify-center border border-[var(--border)] text-[var(--muted)] transition-colors hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"
        >
          {collapsed ? <ChevronsUpDown className="h-3.5 w-3.5" /> : <ChevronsDownUp className="h-3.5 w-3.5" />}
        </button>
      </header>
      <div
        data-panechrome-content="true"
        data-collapsed={collapsed ? "true" : "false"}
        className={collapsed ? "hidden min-h-0 flex-1" : "flex min-h-0 flex-1"}
      >
        {children}
      </div>
    </section>
  );
}
