import { useLayoutEffect, useRef, useState } from "react";
import type { ChatSessionSummary } from "../services/types";

type Props = {
  items: ChatSessionSummary[];
  selectedId: string;
  focusOnMount: boolean;
  onSelect: (session: ChatSessionSummary) => void;
  onCreate?: (title: string) => Promise<ChatSessionSummary>;
};

export function ChatSessionSelector({ items, selectedId, focusOnMount, onSelect, onCreate }: Props) {
  const selectRef = useRef<HTMLSelectElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
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
    if (!onCreate || !name || saving) return;
    const version = ++request.current;
    setSaving(true);
    setError("");
    try {
      const item = await onCreate(name);
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
      <select
        ref={selectRef}
        autoFocus={focusOnMount}
        aria-label="当前聊天会话"
        value={selectedId}
        className="h-8 max-w-[min(30vw,10rem)] shrink-0 truncate rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-1 text-xs text-[var(--text)]"
        onChange={(event) => {
          const selected = items.find((item) => item.id === event.target.value);
          if (selected) {
            onSelect(selected);
          } else if (onCreate) {
            setTitle("");
            setError("");
            dialogRef.current?.showModal();
          }
        }}
      >
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {repeatedTitles.has(item.title) ? `${item.title} · ${item.id === "main" ? "默认" : item.id.slice(-8)}` : item.title}
          </option>
        ))}
        {onCreate ? <option value="">新建聊天会话…</option> : null}
      </select>
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
                required
                maxLength={80}
                disabled={saving}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="mt-2 h-9 w-full rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] px-2"
              />
            </label>
            {error ? <p role="alert" className="mt-2 text-xs text-[var(--status-danger)]">{error}</p> : null}
            <div className="mt-3 flex justify-end gap-2 text-sm">
              <button type="button" disabled={saving} onClick={closeDialog} className="h-8 rounded-md px-3">取消</button>
              <button type="submit" disabled={saving || !title.trim()} className="h-8 rounded-md bg-[var(--accent)] px-3 text-[var(--accent-foreground)] disabled:opacity-60">
                {saving ? "创建中…" : "创建"}
              </button>
            </div>
          </form>
        </dialog>
      ) : null}
    </>
  );
}
