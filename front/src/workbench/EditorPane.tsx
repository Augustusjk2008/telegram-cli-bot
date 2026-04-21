import { clsx } from "clsx";
import { useState } from "react";
import { FileEditorSurface } from "../components/FileEditorSurface";
import type { EditorTab } from "./workbenchTypes";

type Props = {
  tabs: EditorTab[];
  activeTab: EditorTab | null;
  activeTabPath: string;
  breakpointLines?: number[];
  currentLine?: number | null;
  onToggleBreakpoint?: (line: number) => void;
  onActivateTab: (path: string) => void | Promise<void>;
  onCloseTab: (path: string) => boolean;
  onChangeActiveContent: (content: string) => void;
  onSaveActiveTab: () => void;
  onCloseOthers: (path: string) => void;
  onCloseTabsToRight: (path: string) => void;
  onReopenLastClosed: () => void | Promise<void>;
  onRevealInTree: (path: string) => void | Promise<void>;
  focused: boolean;
  onToggleFocus: () => void;
};

export function EditorPane({
  tabs,
  activeTab,
  activeTabPath,
  breakpointLines = [],
  currentLine = null,
  onToggleBreakpoint,
  onActivateTab,
  onCloseTab,
  onChangeActiveContent,
  onSaveActiveTab,
  onCloseOthers,
  onCloseTabsToRight,
  onReopenLastClosed,
  onRevealInTree,
  focused,
  onToggleFocus,
}: Props) {
  const [menuPath, setMenuPath] = useState("");

  if (tabs.length === 0 || !activeTab) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center p-6 text-sm text-[var(--muted)]">
        从左侧文件树打开一个文件开始编辑
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--surface-strong)] px-2 py-1.5">
        <div className="flex min-w-0 items-center gap-1.5 overflow-x-auto">
          {tabs.map((tab) => {
            const isActive = activeTabPath === tab.path;
            return (
              <div
                key={tab.path}
                onContextMenu={(event) => {
                  event.preventDefault();
                  setMenuPath((current) => current === tab.path ? "" : tab.path);
                }}
                className={clsx(
                  "relative flex shrink-0 items-center gap-1 border px-2.5 py-1.5",
                  isActive
                    ? "border-[var(--accent-outline)] bg-[var(--accent-soft)]"
                    : "border-[var(--border)] bg-[var(--surface)]",
                )}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  title={tab.path}
                  onClick={() => {
                    setMenuPath("");
                    void onActivateTab(tab.path);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                      event.preventDefault();
                      setMenuPath(tab.path);
                    }
                  }}
                  className="max-w-52 truncate text-sm text-[var(--text)]"
                >
                  {tab.basename}
                </button>
                {tab.dirty ? (
                  <span
                    data-testid={`editor-tab-dirty-dot-${tab.path}`}
                    className="h-2 w-2 rounded-full bg-[var(--accent)]"
                  />
                ) : null}
                <button
                  type="button"
                  aria-label={`关闭 ${tab.path}`}
                  onClick={() => {
                    if (onCloseTab(tab.path)) {
                      setMenuPath((current) => current === tab.path ? "" : current);
                    }
                  }}
                  className="rounded px-1 text-xs text-[var(--muted)] hover:bg-[var(--surface-strong)]"
                >
                  ×
                </button>
                {menuPath === tab.path ? (
                  <div className="absolute right-0 top-full z-20 mt-2 w-44 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]">
                    <button
                      type="button"
                      onClick={() => {
                        onCloseTab(tab.path);
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      关闭
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        onCloseOthers(tab.path);
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      关闭其他标签页
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        onCloseTabsToRight(tab.path);
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      关闭右侧标签页
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void onReopenLastClosed();
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      重新打开刚关闭的标签页
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void onRevealInTree(tab.path);
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      在文件树中定位
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
        <button
          type="button"
          aria-label={focused ? "退出聚焦编辑器" : "聚焦编辑器"}
          onClick={onToggleFocus}
          className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--surface)]"
        >
          {focused ? "恢复" : "聚焦"}
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

      <div className="min-h-0 flex-1 overflow-hidden">
        <FileEditorSurface
          path={activeTab.path}
          value={activeTab.content}
          loading={activeTab.loading}
          saving={activeTab.saving}
          dirty={activeTab.dirty}
          canSave={activeTab.dirty && !activeTab.missing}
          breakpointLines={breakpointLines}
          currentLine={currentLine}
          statusText=""
          error=""
          hideHeader
          onToggleBreakpoint={onToggleBreakpoint}
          onChange={onChangeActiveContent}
          onSave={onSaveActiveTab}
          onClose={() => {
            onCloseTab(activeTab.path);
          }}
        />
      </div>
    </div>
  );
}
