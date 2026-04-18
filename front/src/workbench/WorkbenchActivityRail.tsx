import { Bot, Files, GitBranch, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { clsx } from "clsx";

type WorkbenchPanelId = "explorer" | "git" | "assistant";

type Props = {
  activePanel: WorkbenchPanelId;
  explorerCollapsed: boolean;
  onToggleExplorer: () => void;
};

const ITEMS: Array<{ id: WorkbenchPanelId; label: string; icon: typeof Files }> = [
  { id: "explorer", label: "资源管理器", icon: Files },
  { id: "git", label: "Git", icon: GitBranch },
  { id: "assistant", label: "AI 助手", icon: Bot },
];

export function WorkbenchActivityRail({ activePanel, explorerCollapsed, onToggleExplorer }: Props) {
  return (
    <aside
      data-testid="desktop-workbench-activity-rail"
      className="flex h-full min-h-0 flex-col items-center gap-2 border-r border-[var(--border)] bg-[var(--surface-strong)] px-2 py-3"
    >
      <button
        type="button"
        aria-label={explorerCollapsed ? "展开资源管理器" : "折叠资源管理器"}
        onClick={onToggleExplorer}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface)]"
      >
        {explorerCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
      </button>
      {ITEMS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          aria-label={label}
          aria-pressed={id === activePanel}
          className={clsx(
            "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-transparent text-[var(--muted)] hover:bg-[var(--surface)] hover:text-[var(--text)]",
            id === activePanel && "border-[var(--border)] bg-[var(--surface)] text-[var(--text)]",
          )}
        >
          <Icon className="h-4 w-4" />
        </button>
      ))}
    </aside>
  );
}
