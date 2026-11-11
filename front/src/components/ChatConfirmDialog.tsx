import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

type Props = {
  /** Accessible name of the dialog. */
  label: string;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "accent" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Small modal confirmation for chat actions. Portalled to body so panel backdrops cannot confine it;
 * `desktop-workbench-popover` keeps the buttons' Tailwind text size and the theme overlay shape there.
 */
export function ChatConfirmDialog({
  label,
  title,
  description,
  confirmLabel,
  cancelLabel = "取消",
  tone = "accent",
  onConfirm,
  onCancel,
}: Props) {
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    confirmButtonRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onCancelRef.current();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      if (previousFocus?.isConnected && document.activeElement === document.body) {
        previousFocus.focus();
      }
    };
  }, []);

  const confirmClassName = tone === "danger"
    ? "inline-flex h-8 items-center rounded-md border border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-3 text-xs font-medium text-[var(--status-danger)] hover:opacity-90"
    : "inline-flex h-8 items-center rounded-md bg-[var(--accent)] px-3 text-xs font-medium text-[var(--accent-foreground)] hover:opacity-90";

  const dialog = (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-[var(--overlay-backdrop-35)] px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="desktop-workbench-popover w-full max-w-sm rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-4 shadow-[var(--shadow-card)]"
      >
        <h2 className="text-sm font-semibold text-[var(--text)]">{title}</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">{description}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-8 items-center rounded-md border border-[var(--workbench-hairline)] px-3 text-xs text-[var(--text)] hover:bg-[var(--surface-strong)]"
          >
            {cancelLabel}
          </button>
          <button ref={confirmButtonRef} type="button" onClick={onConfirm} className={confirmClassName}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );

  return typeof document !== "undefined" ? createPortal(dialog, document.body) : dialog;
}
