import { useState } from "react";
import { CheckCheck } from "lucide-react";

export function ClearUnreadButton({ onClear }: { onClear: () => Promise<void> }) {
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState("");

  async function handleClick() {
    if (clearing) return;
    setClearing(true);
    setError("");
    try {
      await onClear();
    } catch {
      setError("部分未读未能清除，请重试");
    } finally {
      setClearing(false);
    }
  }

  return (
    <span className="relative flex shrink-0 items-center">
      <button
        type="button"
        aria-label="清除全部未读"
        title={clearing ? "正在清除未读…" : "清除全部未读"}
        disabled={clearing}
        onClick={() => void handleClick()}
        className="inline-flex h-[var(--mobile-shell-control,2rem)] w-[var(--mobile-shell-control,2rem)] items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)] focus-visible:outline-2 focus-visible:outline-[var(--accent)] disabled:opacity-40"
      >
        <CheckCheck className="h-4 w-4" aria-hidden="true" />
      </button>
      {error ? (
        <span role="alert" className="absolute right-0 top-full z-50 mt-2 w-52 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--text)] shadow-[var(--shadow-card)]">
          {error}
        </span>
      ) : null}
    </span>
  );
}
