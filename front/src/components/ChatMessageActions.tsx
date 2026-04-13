type Props = {
  elapsedSeconds?: number;
  copyLabel: string;
  onCopy: () => void;
};

export function ChatMessageActions({ elapsedSeconds, copyLabel, onCopy }: Props) {
  return (
    <div className="mt-2 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600">
      {typeof elapsedSeconds === "number" ? <span>用时 {elapsedSeconds} 秒</span> : null}
      <button
        type="button"
        onClick={onCopy}
        className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-700 hover:bg-slate-100"
      >
        {copyLabel}
      </button>
    </div>
  );
}

