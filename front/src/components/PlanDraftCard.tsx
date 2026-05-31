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
    <SurfacePanel className="mt-3 border-emerald-200 bg-emerald-50/80 px-4 py-3 text-sm text-emerald-950 shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-emerald-700">方案草稿</div>
          <div className="mt-1 font-semibold">候选方案</div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => setEditing((value) => !value)}
            className={toolbarButtonClass("plain", "sm", "border-emerald-200 bg-white text-emerald-800 hover:bg-emerald-100")}
          >
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
            {editing ? "收起" : "修改方案"}
          </button>
          <button
            type="button"
            disabled={executing || !effectiveContent.trim()}
            onClick={() => onExecute(effectiveContent)}
            className={toolbarButtonClass("primary", "sm", "bg-emerald-700 text-white hover:bg-emerald-800")}
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
          className="mt-3 min-h-56 w-full rounded-md border border-emerald-200 bg-white p-3 font-mono text-xs leading-5 text-slate-900 outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-200"
        />
      ) : null}
      {error ? <div className="mt-2 text-xs text-red-700">{error}</div> : null}
    </SurfacePanel>
  );
}
