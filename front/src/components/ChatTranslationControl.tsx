import { Languages, LoaderCircle } from "lucide-react";
import type { ChatMessage } from "../services/types";

export function ChatTranslationControl({ item, onChange }: {
  item: ChatMessage;
  onChange: (view: "original" | "translated") => void;
}) {
  const translation = item.translation;
  if (!translation) return null;
  const available = translation.status === "completed" && Boolean(translation.text?.trim());
  const translated = available && item.translationView !== "original";
  const label = available
    ? translated ? "显示原文" : "显示译文"
    : translation.status === "pending" ? "译文待更新，当前为原文" : "翻译未完成，显示原文";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={translated}
      disabled={!available}
      onClick={() => onChange(translated ? "original" : "translated")}
      className={`inline-flex h-6 w-6 items-center justify-center rounded-md border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50 ${translated
        ? "border-[var(--accent-outline)] bg-[var(--accent-soft)] text-[var(--accent)] hover:bg-[var(--workbench-hover-bg)]"
        : "border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--muted)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}`}
    >
      {translation.status === "pending"
        ? <LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
        : <Languages aria-hidden="true" className="h-3.5 w-3.5" />}
    </button>
  );
}
