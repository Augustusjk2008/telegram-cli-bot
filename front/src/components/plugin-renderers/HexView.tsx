import type { HexViewPayload } from "../../services/types";
import { VirtualList } from "../virtual/VirtualList";

type Props = {
  title: string;
  payload: HexViewPayload;
};

function formatOffset(offset: number) {
  return Math.max(0, offset).toString(16).toUpperCase().padStart(8, "0");
}

function entropyColor(entropy: number) {
  const bounded = Math.max(0, Math.min(1, entropy));
  if (bounded >= 0.75) {
    return "bg-[var(--entropy-high)]";
  }
  if (bounded >= 0.45) {
    return "bg-[var(--entropy-medium)]";
  }
  return "bg-[var(--entropy-low)]";
}

export function HexView({ title, payload }: Props) {
  return (
    <div data-testid="hex-view" className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--surface)] text-[var(--text)]">
      <header className="shrink-0 border-b border-[var(--border)] px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="min-w-0 truncate text-sm font-semibold">{title}</h2>
          <span className="rounded border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--muted)]">
            {payload.statsText || `${payload.fileSizeBytes} B`}
          </span>
          {payload.truncated ? (
            <span className="rounded border border-[var(--feedback-warning-border-visible)] bg-[var(--feedback-warning-background-subtle)] px-2 py-0.5 text-xs text-[var(--feedback-warning-text-stronger)]">已截断</span>
          ) : null}
        </div>
        <div className="mt-3 flex h-4 overflow-hidden rounded border border-[var(--border)] bg-[var(--surface-strong)]">
          {payload.entropyBuckets.map((bucket) => (
            <div
              key={bucket.index}
              data-testid="hex-entropy-bucket"
              title={`${formatOffset(bucket.startOffset)}-${formatOffset(bucket.endOffset)} entropy ${bucket.entropy.toFixed(2)}`}
              className={`${entropyColor(bucket.entropy)} min-w-[2px] flex-1`}
              style={{ opacity: 0.35 + Math.max(0, Math.min(1, bucket.entropy)) * 0.65 }}
            />
          ))}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <VirtualList
          key={payload.path}
          items={payload.rows}
          rowHeight={24}
          dataTestId="virtualized-hex-rows"
          className="flex-1 font-mono text-[12px] leading-6"
          getKey={(row) => String(row.offset)}
          renderRow={(row) => (
            <div
              data-testid="hex-row"
              className="grid h-full w-max gap-4 whitespace-pre"
              style={{ gridTemplateColumns: `96px ${payload.bytesPerRow * 3 - 1}ch ${payload.bytesPerRow}ch` }}
            >
              <div className="select-none text-right text-[var(--muted)]">{formatOffset(row.offset)}</div>
              <div className="text-[var(--text)]">{row.hex.join(" ")}</div>
              <div className="text-[var(--muted)]">{row.ascii}</div>
            </div>
          )}
        />
      </div>
    </div>
  );
}
