import { Check, Pencil, X } from "lucide-react";
import { useEffect, useState } from "react";

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
    <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-950">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium">候选方案</div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => setEditing((value) => !value)}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-emerald-200 bg-white px-3 text-xs font-medium text-emerald-800 hover:bg-emerald-100"
          >
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
            {editing ? "收起" : "修改方案"}
          </button>
          <button
            type="button"
            disabled={executing || !effectiveContent.trim()}
            onClick={() => onExecute(effectiveContent)}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-emerald-700 px-3 text-xs font-medium text-white hover:bg-emerald-800 disabled:opacity-60"
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
          className="mt-3 min-h-56 w-full rounded-md border border-emerald-200 bg-white p-3 font-mono text-xs text-slate-900 outline-none focus:border-emerald-500"
        />
      ) : null}
      {error ? <div className="mt-2 text-xs text-red-700">{error}</div> : null}
    </div>
  );
}
