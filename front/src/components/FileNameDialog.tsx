type Props = {
  title: string;
  label: string;
  value: string;
  confirmText: string;
  busy?: boolean;
  error?: string;
  onChange: (value: string) => void;
  onConfirm: () => void;
  onClose: () => void;
};

export function FileNameDialog({
  title,
  label,
  value,
  confirmText,
  busy = false,
  error = "",
  onChange,
  onConfirm,
  onClose,
}: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="w-full max-w-md rounded-2xl bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-[var(--text)]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-3 py-1 text-sm"
          >
            取消
          </button>
        </div>
        <label className="block text-sm text-[var(--text)]" htmlFor="file-name-input">
          {label}
        </label>
        <input
          id="file-name-input"
          autoFocus
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
        />
        {error ? <p className="mt-3 text-sm text-red-600">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-60"
          >
            {busy ? "处理中..." : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
