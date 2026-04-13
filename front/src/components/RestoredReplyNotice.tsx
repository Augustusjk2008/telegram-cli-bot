type Props = {
  disabled?: boolean;
  onContinue: () => void;
};

export function RestoredReplyNotice({ disabled = false, onContinue }: Props) {
  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]">
      <span>上次回复疑似中断，可继续接着处理。</span>
      <button
        type="button"
        onClick={onContinue}
        disabled={disabled}
        className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
      >
        继续
      </button>
    </div>
  );
}

