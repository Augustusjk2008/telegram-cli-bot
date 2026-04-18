import type { ViewMode } from "../app/layoutMode";

type Props = {
  currentPath: string;
  activeFilePath: string;
  isDirty: boolean;
  terminalLabel: string;
  chatLabel: string;
  viewMode: ViewMode;
};

function viewModeLabel(viewMode: ViewMode) {
  if (viewMode === "desktop") {
    return "桌面版";
  }
  if (viewMode === "mobile") {
    return "手机版";
  }
  return "自动";
}

export function WorkbenchStatusBar({
  currentPath,
  activeFilePath,
  isDirty,
  terminalLabel,
  chatLabel,
  viewMode,
}: Props) {
  return (
    <footer
      data-testid="desktop-workbench-statusbar"
      className="flex items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--surface-strong)] px-3 py-1.5 text-xs text-[var(--text)]"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="truncate">{currentPath}</span>
        <span>{activeFilePath ? `${activeFilePath}${isDirty ? " · 未保存" : " · 已保存"}` : "未打开文件"}</span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span>{terminalLabel}</span>
        <span>{chatLabel}</span>
        <span>{viewModeLabel(viewMode)}</span>
      </div>
    </footer>
  );
}
