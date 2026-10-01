import { useState } from "react";
import type { WaveformOverviewBin } from "../../../services/types";
import { overviewBinToX, timeToX, xToTime, type TimeRange } from "./timelineMath";

type Props = {
  fullRange: TimeRange;
  viewRange: TimeRange;
  overview?: { bins: WaveformOverviewBin[] };
  onRangeChange: (range: TimeRange) => void;
  onFitAll: () => void;
  onFitSelected: () => void;
  onStart: () => void;
  onEnd: () => void;
};

const OVERVIEW_WIDTH = 640;

export function WaveformTimelineNavigator({
  fullRange,
  viewRange,
  overview,
  onRangeChange,
  onFitAll,
  onFitSelected,
  onStart,
  onEnd,
}: Props) {
  const [dragStart, setDragStart] = useState<number | null>(null);
  const updateFromX = (x: number, anchor?: number) => {
    const time = xToTime(fullRange.startTime, fullRange.endTime, OVERVIEW_WIDTH, x);
    if (anchor == null) {
      onRangeChange({ startTime: time, endTime: Math.min(fullRange.endTime, time + Math.max(1, viewRange.endTime - viewRange.startTime)) });
      return;
    }
    const length = Math.max(1, Math.abs(time - anchor));
    onRangeChange({ startTime: Math.min(anchor, time), endTime: Math.min(fullRange.endTime, Math.min(anchor, time) + length) });
  };
  return (
    <div className="border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)]" data-testid="waveform-timeline-navigator">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-[var(--text)]">时间导航</strong>
        <button type="button" onClick={onFitAll} className="rounded border border-[var(--border)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)]">适应全部</button>
        <button type="button" onClick={onFitSelected} className="rounded border border-[var(--border)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)]">适应选中</button>
        <button type="button" onClick={onStart} className="rounded border border-[var(--border)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)]">跳到开始</button>
        <button type="button" onClick={onEnd} className="rounded border border-[var(--border)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)]">跳到结束</button>
        <label className="flex items-center gap-1">起 <input aria-label="视图开始时间" type="number" value={viewRange.startTime} onChange={(event) => onRangeChange({ startTime: Number(event.currentTarget.value), endTime: viewRange.endTime })} className="h-7 w-24 rounded border border-[var(--border)] bg-[var(--surface-strong)] px-1 text-[var(--text)]" /></label>
        <label className="flex items-center gap-1">止 <input aria-label="视图结束时间" type="number" value={viewRange.endTime} onChange={(event) => onRangeChange({ startTime: viewRange.startTime, endTime: Number(event.currentTarget.value) })} className="h-7 w-24 rounded border border-[var(--border)] bg-[var(--surface-strong)] px-1 text-[var(--text)]" /></label>
      </div>
      <svg
        width="100%"
        height="34"
        viewBox={`0 0 ${OVERVIEW_WIDTH} 34`}
        preserveAspectRatio="none"
        className="mt-2 block h-8 w-full cursor-ew-resize rounded bg-[var(--surface-strong)]"
        data-testid="waveform-overview"
        onPointerDown={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * OVERVIEW_WIDTH;
          setDragStart(xToTime(fullRange.startTime, fullRange.endTime, OVERVIEW_WIDTH, x));
          updateFromX(x);
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (dragStart == null) return;
          const rect = event.currentTarget.getBoundingClientRect();
          const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * OVERVIEW_WIDTH;
          updateFromX(x, dragStart);
        }}
        onPointerUp={() => setDragStart(null)}
        onPointerCancel={() => setDragStart(null)}
      >
        {(overview?.bins || []).map((bin) => {
          const { startX, endX } = overviewBinToX(bin, fullRange.startTime, fullRange.endTime, OVERVIEW_WIDTH);
          return <rect key={`${bin.start}-${bin.end}`} x={startX} y="8" width={Math.max(1, endX - startX)} height="18" fill="var(--waveform-dense-fill)" opacity="0.8" />;
        })}
        <rect x={timeToX(fullRange.startTime, fullRange.endTime, OVERVIEW_WIDTH, viewRange.startTime)} y="3" width={Math.max(2, timeToX(fullRange.startTime, fullRange.endTime, OVERVIEW_WIDTH, viewRange.endTime) - timeToX(fullRange.startTime, fullRange.endTime, OVERVIEW_WIDTH, viewRange.startTime))} height="28" fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
      <div className="mt-1 flex justify-between font-mono text-[10px]"><span>{fullRange.startTime}</span><span>{fullRange.endTime}</span></div>
    </div>
  );
}
