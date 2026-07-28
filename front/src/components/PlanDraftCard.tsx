import { Check, Pencil, X } from "lucide-react";
import { useEffect, useState } from "react";
import { SurfacePanel } from "./SurfacePanel";
import { toolbarButtonClass } from "./ToolbarButton";

type Props = {
  content: string;
  executing?: boolean;
  error?: string;
  onExecute: (content: string) => void;
};

export function PlanDraftCard({ content, executing = false, error = "", onExecute }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);

  useEffect(() => {
    setDraft(content);
  }, [content]);

  const effectiveContent = editing ? draft : content;

  return (
    <SurfacePanel className="mt-3 border-[var(--status-success-border)] bg-[var(--status-success-bg)] px-3 py-2 text-sm text-[var(--text)] shadow-[var(--shadow-surface)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--status-success)]">方案草稿</div>
          <div className="mt-1 font-semibold">候选方案</div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => setEditing((value) => !value)}
            className={toolbarButtonClass("plain", "sm", "border-[var(--status-success-border)] bg-[var(--workbench-panel-elevated-bg)] text-[var(--status-success)] hover:bg-[var(--status-success-bg)]")}
          >
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
            {editing ? "收起" : "修改方案"}
          </button>
          <button
            type="button"
            disabled={executing || !effectiveContent.trim()}
            onClick={() => onExecute(effectiveContent)}
            className={toolbarButtonClass("primary", "sm", "hover:opacity-90")}
          >
            <Check className="h-3.5 w-3.5" />
            {executing ? "执行中" : "执行方案"}
          </button>
        </div>
      </div>
      {editing ? (
        <textarea
          aria-label="方案内容"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="mt-3 min-h-56 w-full rounded-md border border-[var(--status-success-border)] bg-[var(--workbench-panel-elevated-bg)] p-3 font-mono text-xs leading-5 text-[var(--text)] outline-none focus:border-[var(--status-success)] focus:ring-2 focus:ring-[var(--status-success-border)]"
        />
      ) : null}
      {error ? <div className="mt-2 text-xs text-[var(--status-danger)]">{error}</div> : null}
    </SurfacePanel>
  );
}
