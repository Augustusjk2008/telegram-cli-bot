import { FileEditorSurface } from "../components/FileEditorSurface";
import type { EditorTab } from "./workbenchTypes";

type Props = {
  tabs: EditorTab[];
  activeTab: EditorTab | null;
  activeTabPath: string;
  onActivateTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  onChangeActiveContent: (content: string) => void;
  onSaveActiveTab: () => void;
};

export function EditorPane({
  tabs,
  activeTab,
  activeTabPath,
  onActivateTab,
  onCloseTab,
  onChangeActiveContent,
  onSaveActiveTab,
}: Props) {
  if (tabs.length === 0 || !activeTab) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center p-6 text-sm text-[var(--muted)]">
        从左侧文件树打开一个文件开始编辑
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 overflow-x-auto border-b border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2">
        {tabs.map((tab) => (
          <div
            key={tab.path}
            className="flex shrink-0 items-center gap-1 rounded-xl border border-[var(--border)] bg-[var(--surface)] pl-3 pr-2"
          >
            <button
              type="button"
              role="tab"
              aria-selected={activeTabPath === tab.path}
              onClick={() => onActivateTab(tab.path)}
              className="py-2 text-sm text-[var(--text)]"
            >
              {tab.path}
              {tab.dirty ? " *" : ""}
            </button>
            <button
              type="button"
              aria-label={`关闭 ${tab.path}`}
              onClick={() => onCloseTab(tab.path)}
              className="rounded-lg px-1 py-1 text-xs text-[var(--muted)] hover:bg-[var(--surface-strong)]"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[var(--text)]">{activeTab.path}</p>
          <p className="text-xs text-[var(--muted)]">{activeTab.dirty ? "有未保存修改" : "已与磁盘同步"}</p>
        </div>
        <button
          type="button"
          onClick={onSaveActiveTab}
          disabled={!activeTab.dirty || activeTab.loading || activeTab.saving}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {activeTab.saving ? "保存中..." : "保存"}
        </button>
      </div>

      {activeTab.statusText ? (
        <div className="border-b border-[var(--border)] px-4 py-2 text-sm text-[var(--muted)]">
          {activeTab.statusText}
        </div>
      ) : null}
      {activeTab.error ? (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {activeTab.error}
        </div>
      ) : null}

      <div className="flex-1 min-h-0">
        <FileEditorSurface
          path={activeTab.path}
          value={activeTab.content}
          loading={activeTab.loading}
          saving={activeTab.saving}
          dirty={activeTab.dirty}
          canSave={activeTab.dirty}
          statusText=""
          error=""
          hideHeader
          onChange={onChangeActiveContent}
          onSave={onSaveActiveTab}
          onClose={() => onCloseTab(activeTab.path)}
        />
      </div>
    </div>
  );
}
