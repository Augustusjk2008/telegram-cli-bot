import { clsx } from "clsx";
import { BookOpenCheck, Bug, Files, Gauge, GitBranch, ListTree, PanelLeftClose, PanelLeftOpen, Puzzle, Search, Settings2 } from "lucide-react";
import type { WorkbenchActivityId } from "./workbenchTypes";

type Props = {
  activeItem: WorkbenchActivityId;
  sidebarCollapsed: boolean;
  availableItems?: WorkbenchActivityId[];
  onToggleSidebar: () => void;
  onSelectItem: (item: WorkbenchActivityId) => void;
};

const ITEMS: Array<{ id: WorkbenchActivityId; label: string; icon: typeof Files }> = [
  { id: "files", label: "文件", icon: Files },
  { id: "search", label: "搜索", icon: Search },
  { id: "outline", label: "大纲", icon: ListTree },
  { id: "guide", label: "指南", icon: BookOpenCheck },
  { id: "debug", label: "调试", icon: Bug },
  { id: "git", label: "Git", icon: GitBranch },
  { id: "assistant-ops", label: "运维", icon: Gauge },
  { id: "plugins", label: "插件", icon: Puzzle },
  { id: "settings", label: "设置", icon: Settings2 },
];

export function WorkbenchActivityRail({
  activeItem,
  sidebarCollapsed,
  availableItems,
  onToggleSidebar,
  onSelectItem,
}: Props) {
  const items = availableItems?.length
    ? ITEMS.filter((item) => availableItems.includes(item.id))
    : ITEMS;
  return (
    <aside
      data-testid="desktop-workbench-activity-rail"
      className="workbench-activity-rail flex h-full min-h-0 flex-col items-center gap-1.5 border-r border-[var(--workbench-hairline)] bg-[var(--workbench-sidebar-bg)] px-1.5 py-2"
    >
      <button
        type="button"
        aria-label={sidebarCollapsed ? "展开侧边栏" : "折叠侧边栏"}
        onClick={onToggleSidebar}
        className="workbench-rail-toggle inline-flex h-9 w-9 items-center justify-center border border-[var(--border)] bg-[var(--surface-glass)] text-[var(--text)] transition-colors hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]"
      >
        {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
      </button>
      <div className="my-1 h-px w-6 bg-[var(--workbench-hairline)]" aria-hidden="true" />
      {items.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          aria-label={label}
          aria-pressed={id === activeItem}
          data-workbench-activity-id={id}
          data-active={id === activeItem ? "true" : "false"}
          onClick={() => onSelectItem(id)}
          className={clsx(
            "workbench-activity-button inline-flex h-9 w-9 items-center justify-center border border-transparent text-[var(--muted)] transition-colors hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]",
            id === activeItem && "bg-[var(--workbench-active-bg)] text-[var(--accent)]",
          )}
        >
          <Icon className="h-4 w-4" />
        </button>
      ))}
    </aside>
  );
}
