import { useId, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, LoaderCircle } from "lucide-react";
import type { ChatSessionList, ChatSessionSummary, CliType } from "../services/types";
import { cliTypeLabel } from "../utils/cliType";

type Props = {
  items: ChatSessionSummary[];
  cliOptions?: ChatSessionList["cliOptions"];
  selectedId: string;
  activeCliType?: CliType;
  activeTurnRunning?: boolean;
  focusOnMount: boolean;
  onSelect: (session: ChatSessionSummary) => void;
  onCreate?: (title: string, cliType?: CliType) => Promise<ChatSessionSummary>;
};

export function ChatSessionSelector({ items, cliOptions, selectedId, activeCliType, activeTurnRunning, focusOnMount, onSelect, onCreate }: Props) {
  const selectRef = useRef<HTMLSelectElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const toolRef = useRef<HTMLSelectElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const availabilityId = useId();
  const [title, setTitle] = useState("");
  const [choices, setChoices] = useState<Props["cliOptions"]>();
  const [cliType, setCliType] = useState<CliType>();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const request = useRef(0);
  const selectCreated = useRef(onSelect);
  selectCreated.current = onSelect;
  const titles = new Set<string>();
  const repeatedTitles = new Set<string>();
  for (const item of items) {
    if (titles.has(item.title)) repeatedTitles.add(item.title);
    titles.add(item.title);
  }
  function toolLabel(item: ChatSessionSummary) {
    if (!item.effectiveCliType) return "";
    if (item.effectiveCliType === "unknown") return "未知工具";
    const label = cliTypeLabel(item.id === selectedId && activeCliType ? activeCliType : item.effectiveCliType);
    return item.selectedCliType ? label : `${label}（Bot 默认）`;
  }
  const active = items.find((item) => item.id === selectedId);
  const activeTool = active && toolLabel(active);
  function activityLabel(item: ChatSessionSummary) {
    if (item.isProcessing || (item.id === selectedId && activeTurnRunning)) return "处理中";
    return item.isProcessing === false ? "空闲" : "";
  }
  const activeBusy = active && activityLabel(active) === "处理中";
  const canCreate = Boolean(title.trim()) && !saving
    && (!choices || choices.some((item) => item.cliType === cliType && item.available));
  const hasUnavailable = choices && (!choices.length || choices.some((item) => !item.available));

  function sessionTitle(item: ChatSessionSummary) {
    const suffix = repeatedTitles.has(item.title) && (item.id === "main" ? "默认" : item.id.slice(-8));
    return suffix ? `${item.title} · ${suffix}` : item.title;
  }

  useLayoutEffect(() => {
    if (error) (toolRef.current || inputRef.current)?.focus();
  }, [error]);

  useLayoutEffect(() => {
    setSaving(false);
    return () => { request.current++; };
  }, [onCreate]);

  function closeDialog() {
    if (saving) return;
    request.current++;
    dialogRef.current?.close();
    selectRef.current?.focus();
  }

  async function submit() {
    const name = title.trim();
    if (!onCreate || !canCreate) return;
    const version = ++request.current;
    setSaving(true);
    setError("");
    try {
      const item = choices ? await onCreate(name, cliType) : await onCreate(name);
      if (request.current === version) selectCreated.current(item);
    } catch (err) {
      if (request.current === version) {
        setError(err instanceof Error ? err.message : "创建聊天会话失败");
        setSaving(false);
      }
    }
  }

  return (
    <>
      <div className="relative max-w-[min(31vw,11rem)] shrink-0">
        <select
          ref={selectRef}
          autoFocus={focusOnMount}
          aria-label="当前聊天会话"
          value={selectedId}
          title={activeTool ? [sessionTitle(active), activeTool, activeBusy ? "处理中" : ""].filter(Boolean).join(" · ") : undefined}
          className={`h-8 max-w-full truncate rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-1 text-xs ${activeTool ? "appearance-none pr-5 text-transparent!" : "text-[var(--text)]"}`}
          onChange={(event) => {
            const selected = items.find((item) => item.id === event.target.value);
            if (selected) {
              onSelect(selected);
            } else if (onCreate) {
              setTitle("");
              setError("");
              setChoices(cliOptions);
              const defaultCli = items.find((item) => item.id === "main")?.effectiveCliType;
              setCliType(defaultCli === "unknown" ? undefined : defaultCli);
              dialogRef.current?.showModal();
              inputRef.current?.focus();
            }
          }}
        >
          {items.map((item) => (
            <option key={item.id} value={item.id} className="text-[var(--text)]">
              {[sessionTitle(item), toolLabel(item), activityLabel(item)].filter(Boolean).join(" · ")}
            </option>
          ))}
          {onCreate ? <option value="" className="text-[var(--text)]">新建聊天会话…</option> : null}
        </select>
        {activeTool ? (
          <span aria-hidden="true" className="pointer-events-none absolute inset-0 flex items-center gap-1 px-1.5 text-[var(--text)]">
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="flex min-w-0 items-center gap-1 text-xs leading-tight">
                {activeBusy && <LoaderCircle className="h-3 w-3 shrink-0 animate-spin text-[var(--feedback-warning-text-deep)]" />}
                <span className="truncate">{sessionTitle(active)}</span>
              </span>
              <span className="truncate text-[10px] leading-tight text-[var(--muted)]">{activeTool}</span>
            </span>
            <ChevronDown className="h-3 w-3 shrink-0" />
          </span>
        ) : null}
      </div>
      {onCreate ? (
        <dialog
          ref={dialogRef}
          aria-label="新建聊天会话"
          className="fixed inset-0 m-auto w-[min(22rem,90vw)] rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-4 text-[var(--text)] shadow-[var(--shadow-card)] backdrop:bg-[var(--overlay-backdrop-35)]"
          onCancel={(event) => { event.preventDefault(); closeDialog(); }}
        >
          <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
            <label className="block text-sm font-medium">
              聊天会话名称
              <input
                ref={inputRef}
                required
                maxLength={80}
                disabled={saving}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="mt-2 h-9 w-full rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] px-2"
              />
            </label>
            {choices && (
              <>
                <label className="mt-3 block text-sm font-medium">
                  AI 工具
                  <select
                    ref={toolRef}
                    value={cliType ?? ""}
                    disabled={saving}
                    aria-describedby={hasUnavailable ? availabilityId : undefined}
                    onChange={(event) => setCliType(choices.find((item) => item.cliType === event.target.value)?.cliType)}
                    className="mt-2 h-9 w-full rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] px-2"
                  >
                    {!choices.some((item) => item.cliType === cliType) && <option value="" disabled>请选择工具</option>}
                    {choices.map((option) => (
                      <option key={option.cliType} value={option.cliType} disabled={!option.available}>
                        {cliTypeLabel(option.cliType)}{option.available ? "" : "（不可用）"}
                      </option>
                    ))}
                  </select>
                </label>
                {hasUnavailable && (
                  <p id={availabilityId} className="mt-1 text-xs text-[var(--muted)]">
                    {choices.some((item) => item.available) ? "此主机未找到标为不可用的工具。请选择可用工具。" : "此主机未找到可用的 AI 工具。"}
                  </p>
                )}
              </>
            )}
            {error ? <p role="alert" className="mt-2 text-xs text-[var(--status-danger)]">{error}</p> : null}
            <div className="mt-3 flex justify-end gap-2 text-sm">
              <button type="button" disabled={saving} onClick={closeDialog} className="h-8 rounded-md px-3">取消</button>
              <button type="submit" disabled={!canCreate} className="h-8 rounded-md bg-[var(--accent)] px-3 text-[var(--accent-foreground)] disabled:opacity-60">
                {saving ? "创建中…" : "创建"}
              </button>
            </div>
          </form>
        </dialog>
      ) : null}
    </>
  );
}
