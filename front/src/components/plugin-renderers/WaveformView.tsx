import type { WaveformTrack, WaveformTrackSegment, WaveformViewPayload } from "../../services/types";

type Props = {
  title: string;
  payload: WaveformViewPayload;
};

const TRACK_WIDTH = 840;
const TRACK_HEIGHT = 56;

function trackLevel(value: string) {
  if (value === "1") {
    return 14;
  }
  if (value === "0") {
    return TRACK_HEIGHT - 14;
  }
  return TRACK_HEIGHT / 2;
}

function segmentPosition(segment: WaveformTrackSegment, payload: WaveformViewPayload) {
  const total = Math.max(1, payload.endTime - payload.startTime);
  const start = Math.max(payload.startTime, segment.start);
  const end = Math.max(start, segment.end);
  return {
    startX: ((start - payload.startTime) / total) * TRACK_WIDTH,
    endX: ((end - payload.startTime) / total) * TRACK_WIDTH,
  };
}

function WaveformTrackRow({ payload, track }: { payload: WaveformViewPayload; track: WaveformTrack }) {
  return (
    <div className="grid grid-cols-[220px_minmax(0,1fr)] border-b border-[var(--border)]">
      <div className="px-4 py-3">
        <div className="text-sm font-medium text-[var(--text)]">{track.label}</div>
        <div className="mt-1 text-xs text-[var(--muted)]">{track.width} bit</div>
      </div>
      <div className="overflow-x-auto px-3 py-2">
        <svg
          width={TRACK_WIDTH}
          height={TRACK_HEIGHT}
          viewBox={`0 0 ${TRACK_WIDTH} ${TRACK_HEIGHT}`}
          className="rounded-lg bg-[var(--surface-strong)] text-[var(--text)]"
        >
          <line
            x1="0"
            y1={TRACK_HEIGHT / 2}
            x2={TRACK_WIDTH}
            y2={TRACK_HEIGHT / 2}
            stroke="currentColor"
            strokeOpacity="0.16"
            strokeDasharray="4 6"
          />
          {track.segments.map((segment, index) => {
            const { startX, endX } = segmentPosition(segment, payload);
            const y = trackLevel(segment.value);
            const centerX = startX + Math.max(12, endX - startX) / 2;
            return (
              <g key={`${track.signalId}-${index}`}>
                <line x1={startX} y1={y} x2={endX} y2={y} stroke="currentColor" strokeWidth="2" />
                <line x1={startX} y1="8" x2={startX} y2={TRACK_HEIGHT - 8} stroke="currentColor" strokeOpacity="0.18" />
                <text x={centerX} y={y - 6} textAnchor="middle" fontSize="11">
                  {segment.value}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export function WaveformView({ title, payload }: Props) {
  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface)]">
      <header className="border-b border-[var(--border)] px-4 py-3">
        <h2 className="text-base font-semibold text-[var(--text)]">{title}</h2>
        <p className="mt-1 text-xs text-[var(--muted)]">
          <span>{payload.path}</span>
          <span> · </span>
          <span>{payload.timescale}</span>
          <span> · </span>
          <span>{payload.startTime}</span>
          <span> - </span>
          <span>{payload.endTime}</span>
        </p>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">
        {payload.tracks.length > 0 ? (
          payload.tracks.map((track) => (
            <WaveformTrackRow key={track.signalId} payload={payload} track={track} />
          ))
        ) : (
          <div className="p-4 text-sm text-[var(--muted)]">无波形数据</div>
        )}
      </div>
    </section>
  );
}
