import { clsx } from "clsx";
import { Bug, Files, GitBranch, ListTree, PanelLeftClose, PanelLeftOpen, Search, Settings2 } from "lucide-react";
import type { DesktopSidebarView } from "./workbenchTypes";

type Props = {
  activePanel: DesktopSidebarView;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onSelectPanel: (panel: DesktopSidebarView) => void;
};

const ITEMS: Array<{ id: DesktopSidebarView; label: string; icon: typeof Files }> = [
  { id: "files", label: "文件", icon: Files },
  { id: "search", label: "搜索", icon: Search },
  { id: "outline", label: "大纲", icon: ListTree },
  { id: "debug", label: "调试", icon: Bug },
  { id: "git", label: "Git", icon: GitBranch },
  { id: "settings", label: "设置", icon: Settings2 },
];

export function WorkbenchActivityRail({
  activePanel,
  sidebarCollapsed,
  onToggleSidebar,
  onSelectPanel,
}: Props) {
  return (
    <aside
      data-testid="desktop-workbench-activity-rail"
      className="flex h-full min-h-0 flex-col items-center gap-2 border-r border-[var(--border)] bg-[var(--surface-strong)] px-2 py-3"
    >
      <button
        type="button"
        aria-label={sidebarCollapsed ? "展开侧边栏" : "折叠侧边栏"}
        onClick={onToggleSidebar}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface)]"
      >
        {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
      </button>
      {ITEMS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          aria-label={label}
          aria-pressed={id === activePanel}
          onClick={() => onSelectPanel(id)}
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
