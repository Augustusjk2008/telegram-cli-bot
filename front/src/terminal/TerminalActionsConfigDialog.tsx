import { ArrowDown, ArrowUp, ChevronDown, Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { TerminalAction, TerminalActionsConfig, TerminalActionsEditableConfig } from "../services/types";
import {
  TERMINAL_ACTION_ICON_OPTIONS,
  getTerminalActionIcon,
  getTerminalActionIconLabel,
} from "./terminalActionIcons";

type Props = {
  config: TerminalActionsConfig;
  saving: boolean;
  error: string;
  onSave: (config: TerminalActionsEditableConfig) => void;
  onClose: () => void;
};

function createAction(index: number): TerminalAction {
  return {
    id: `action-${index + 1}`,
    label: "新命令",
    icon: "Terminal",
    windowsCommand: "",
    linuxCommand: "",
    cwd: ".",
    confirm: false,
    enabled: true,
  };
}

function normalizeActions(actions: TerminalAction[]): TerminalAction[] {
  return actions.map((action) => ({
    id: action.id.trim(),
    label: action.label.trim(),
    icon: action.icon.trim() || "Terminal",
    windowsCommand: action.windowsCommand.trim(),
    linuxCommand: action.linuxCommand.trim(),
    cwd: action.cwd.trim() || ".",
    confirm: Boolean(action.confirm),
    enabled: Boolean(action.enabled),
  }));
}

export function TerminalActionsConfigDialog({
  config,
  saving,
  error,
  onSave,
  onClose,
}: Props) {
  const [actions, setActions] = useState<TerminalAction[]>(() => config.actions.map((action) => ({ ...action })));
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const selected = actions[selectedIndex] ?? null;

  const validationMessage = useMemo(() => {
    const seen = new Set<string>();
    for (const action of normalizeActions(actions)) {
      if (!action.id) return "ID 不能为空";
      if (seen.has(action.id)) return `ID 重复: ${action.id}`;
      seen.add(action.id);
      if (!action.label) return "名称不能为空";
      if (!action.windowsCommand && !action.linuxCommand) return "Windows/Linux 命令至少填一个";
    }
    return "";
  }, [actions]);

  function updateSelected(patch: Partial<TerminalAction>) {
    setActions((current) => current.map((action, index) => (index === selectedIndex ? { ...action, ...patch } : action)));
  }

  function addAction() {
    setActions((current) => {
      const next = [...current, createAction(current.length)];
      setSelectedIndex(next.length - 1);
      return next;
    });
  }

  function removeSelected() {
    setActions((current) => {
      const next = current.filter((_action, index) => index !== selectedIndex);
      setSelectedIndex(Math.max(0, Math.min(selectedIndex, next.length - 1)));
      return next;
    });
  }

  function moveSelected(delta: -1 | 1) {
    setActions((current) => {
      const nextIndex = selectedIndex + delta;
      if (nextIndex < 0 || nextIndex >= current.length) {
        return current;
      }
      const next = [...current];
      const [item] = next.splice(selectedIndex, 1);
      next.splice(nextIndex, 0, item);
      setSelectedIndex(nextIndex);
      return next;
    });
  }

  useEffect(() => {
    setIconPickerOpen(false);
  }, [selectedIndex]);

  const SelectedIcon = getTerminalActionIcon(selected?.icon);
  const selectedIconLabel = getTerminalActionIconLabel(selected?.icon);
  const footerError = error || validationMessage;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4" role="dialog" aria-modal="true" aria-labelledby="terminal-actions-title">
      <section className="flex max-h-[86vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)]">
        <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
          <div className="min-w-0">
            <h2 id="terminal-actions-title" className="text-base font-semibold text-[var(--text)]">终端快捷命令</h2>
            <p className="truncate text-xs text-[var(--muted)]">{config.configPath}</p>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose} className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-[var(--surface-strong)]">
            <X className="h-4 w-4" />
          </button>
        </header>

        {config.errors.length > 0 ? (
          <div className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {config.errors.join("；")}
          </div>
        ) : null}

        <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)] overflow-hidden">
          <aside className="min-h-0 overflow-y-auto border-r border-[var(--border)] p-3">
            <button type="button" onClick={addAction} className="mb-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]">
              <Plus className="h-4 w-4" />
              新增快捷命令
            </button>
            <div className="space-y-1">
              {actions.map((action, index) => {
                const Icon = getTerminalActionIcon(action.icon);
                return (
                  <button
                    key={`${action.id}-${index}`}
                    type="button"
                    onClick={() => setSelectedIndex(index)}
                    className={`flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-2 text-left text-sm ${index === selectedIndex ? "bg-[var(--surface-strong)] text-[var(--text)]" : "text-[var(--muted)] hover:bg-[var(--surface-strong)]"}`}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{action.label || action.id || "未命名"}</span>
                  </button>
                );
              })}
            </div>
          </aside>

          <div className="min-h-0 overflow-y-auto p-4">
            {selected ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" aria-label="上移" onClick={() => moveSelected(-1)} disabled={selectedIndex <= 0} className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] disabled:opacity-50">
                    <ArrowUp className="h-4 w-4" />
                  </button>
                  <button type="button" aria-label="下移" onClick={() => moveSelected(1)} disabled={selectedIndex >= actions.length - 1} className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] disabled:opacity-50">
                    <ArrowDown className="h-4 w-4" />
                  </button>
                  <button type="button" aria-label="删除" onClick={removeSelected} className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-red-200 text-red-700 hover:bg-red-50">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-1 text-sm">
                    <span className="font-medium text-[var(--text)]">ID</span>
                    <input aria-label="ID" value={selected.id} onChange={(event) => updateSelected({ id: event.target.value })} className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm" />
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium text-[var(--text)]">名称</span>
                    <input aria-label="名称" value={selected.label} onChange={(event) => updateSelected({ label: event.target.value })} className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" />
                  </label>
                </div>

                <div className="space-y-1 text-sm">
                  <span className="font-medium text-[var(--text)]">平台命令</span>
                  <div className="grid gap-4 md:grid-cols-2">
                    <label className="space-y-1 text-sm">
                      <span className="font-medium text-[var(--text)]">Windows 命令</span>
                      <textarea
                        aria-label="Windows 命令"
                        rows={3}
                        value={selected.windowsCommand}
                        onChange={(event) => updateSelected({ windowsCommand: event.target.value })}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm"
                      />
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="font-medium text-[var(--text)]">Linux 命令</span>
                      <textarea
                        aria-label="Linux 命令"
                        rows={3}
                        value={selected.linuxCommand}
                        onChange={(event) => updateSelected({ linuxCommand: event.target.value })}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm"
                      />
                    </label>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-1 text-sm">
                    <span className="font-medium text-[var(--text)]">工作目录</span>
                    <input aria-label="工作目录" value={selected.cwd} onChange={(event) => updateSelected({ cwd: event.target.value })} className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm" />
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium text-[var(--text)]">图标</span>
                    <div>
                      <button
                        type="button"
                        aria-label="选择图标"
                        aria-haspopup="listbox"
                        aria-expanded={iconPickerOpen}
                        onClick={() => setIconPickerOpen((open) => !open)}
                        className="flex w-full items-center justify-between rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <SelectedIcon className="h-5 w-5 shrink-0" />
                          <span className="truncate">{selectedIconLabel}</span>
                        </span>
                        <ChevronDown className={`h-4 w-4 shrink-0 text-[var(--muted)] transition-transform ${iconPickerOpen ? "rotate-180" : ""}`} />
                      </button>
                      {iconPickerOpen ? (
                        <div role="listbox" aria-label="图标列表" className="mt-2 max-h-72 overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--surface-strong)] p-3">
                          <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">
                            {TERMINAL_ACTION_ICON_OPTIONS.map((icon) => {
                              const Icon = getTerminalActionIcon(icon);
                              const iconLabel = getTerminalActionIconLabel(icon);
                              const active = icon === selected.icon;
                              return (
                                <button
                                  key={icon}
                                  type="button"
                                  role="option"
                                  aria-label={iconLabel}
                                  aria-selected={active}
                                  title={`${iconLabel} (${icon})`}
                                  onClick={() => {
                                    updateSelected({ icon });
                                    setIconPickerOpen(false);
                                  }}
                                  className={`flex aspect-square flex-col items-center justify-center gap-2 rounded-md border px-2 py-2 text-center text-xs ${active ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--text)]" : "border-[var(--border)] bg-[var(--surface)] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]"}`}
                                >
                                  <Icon className="h-5 w-5 shrink-0" />
                                  <span className="leading-4">{iconLabel}</span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </label>
                </div>

                <div className="flex flex-wrap gap-4">
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={selected.enabled} onChange={(event) => updateSelected({ enabled: event.target.checked })} />
                    启用
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={selected.confirm} onChange={(event) => updateSelected({ confirm: event.target.checked })} />
                    执行前确认
                  </label>
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-[var(--border)] px-4 py-8 text-center text-sm text-[var(--muted)]">暂无快捷命令</div>
            )}
          </div>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-4 py-3">
          <div className="min-w-0 text-sm text-red-600">{footerError}</div>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]">取消</button>
            <button
              type="button"
              onClick={() => onSave({ schemaVersion: 1, actions: normalizeActions(actions) })}
              disabled={saving || Boolean(validationMessage) || !config.editable}
              className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
            >
              {!config.editable ? "无保存权限" : saving ? "保存中..." : "保存快捷命令"}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
