import type { ChatMessage } from "../services/types";

export function ChatTranslationControl({ item, onChange }: {
  item: ChatMessage;
  onChange: (view: "original" | "translated") => void;
}) {
  const translation = item.translation;
  if (!translation) return null;
  if (translation.status !== "completed" || !translation.text?.trim()) {
    return <div className="mb-1 text-xs opacity-70">{translation.status === "pending" ? "译文待更新，当前为原文" : "翻译未完成，显示原文"}</div>;
  }
  const view = item.translationView || "translated";
  return (
    <div role="group" aria-label="消息语言版本" className="mb-1 flex flex-wrap items-center gap-1 text-xs">
      {([ ["original", "原文"], ["translated", "译文"] ] as const).map(([value, label]) => (
        <button key={value} type="button" aria-pressed={view === value} onClick={() => onChange(value)}
          className={`rounded px-2 py-1 hover:opacity-80 ${view === value ? "bg-current/10 font-semibold underline underline-offset-4" : "opacity-70"}`}>
          {label}
        </button>
      ))}
      <span className="opacity-70">{translation.target_language}</span>
    </div>
  );
}
