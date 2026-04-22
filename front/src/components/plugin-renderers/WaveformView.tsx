import { useState } from "react";
import type { WaveformTrack, WaveformTrackSegment, WaveformViewPayload } from "../../services/types";

type Props = {
  title: string;
  payload: WaveformViewPayload;
};

const LABEL_WIDTH = 220;
const MIN_WAVE_WIDTH = 840;
const BASE_PIXELS_PER_TIME = 18;
const AXIS_HEIGHT = 42;
const TRACK_HEIGHT = 64;
const HIGH_Y = 16;
const LOW_Y = TRACK_HEIGHT - 16;
const BUS_TOP_Y = 18;
const BUS_BOTTOM_Y = TRACK_HEIGHT - 18;
const BUS_MID_Y = TRACK_HEIGHT / 2;
const ZOOM_STEPS = [0.5, 0.75, 1, 1.5, 2, 3, 4] as const;

function isBusTrack(track: WaveformTrack) {
  return track.width > 1 || track.segments.some((segment) => segment.value.length > 1);
}

function digitalLevel(value: string) {
  if (value === "1") {
    return HIGH_Y;
  }
  if (value === "0") {
    return LOW_Y;
  }
  return BUS_MID_Y;
}

function getRange(payload: WaveformViewPayload) {
  return Math.max(1, payload.endTime - payload.startTime);
}

function getContentWidth(payload: WaveformViewPayload, zoom: number) {
  return Math.max(MIN_WAVE_WIDTH, getRange(payload) * BASE_PIXELS_PER_TIME * zoom);
}

function timeToX(payload: WaveformViewPayload, width: number, time: number) {
  const clamped = Math.min(payload.endTime, Math.max(payload.startTime, time));
  return ((clamped - payload.startTime) / getRange(payload)) * width;
}

function clipSegment(segment: WaveformTrackSegment, payload: WaveformViewPayload) {
  const start = Math.max(payload.startTime, segment.start);
  const end = Math.min(payload.endTime, Math.max(start, segment.end));
  return end > start ? { start, end } : null;
}

function niceStep(rawStep: number) {
  const exponent = Math.floor(Math.log10(Math.max(rawStep, 1)));
  const base = 10 ** exponent;
  const fraction = rawStep / base;
  if (fraction <= 1) {
    return base;
  }
  if (fraction <= 2) {
    return 2 * base;
  }
  if (fraction <= 5) {
    return 5 * base;
  }
  return 10 * base;
}

function buildTicks(payload: WaveformViewPayload, width: number) {
  const range = getRange(payload);
  const targetCount = Math.max(2, Math.floor(width / 96));
  const step = niceStep(range / targetCount);
  const first = Math.ceil(payload.startTime / step) * step;
  const ticks: number[] = [];
  for (let time = first; time <= payload.endTime; time += step) {
    ticks.push(time);
  }
  if (!ticks.includes(payload.startTime)) {
    ticks.unshift(payload.startTime);
  }
  if (!ticks.includes(payload.endTime)) {
    ticks.push(payload.endTime);
  }
  return ticks;
}

function buildDigitalPath(track: WaveformTrack, payload: WaveformViewPayload, width: number) {
  let path = "";
  let previousY: number | null = null;

  track.segments.forEach((segment) => {
    const clipped = clipSegment(segment, payload);
    if (!clipped) {
      return;
    }
    const startX = timeToX(payload, width, clipped.start);
    const endX = timeToX(payload, width, clipped.end);
    const y = digitalLevel(segment.value);
    if (!path) {
      path = `M ${startX} ${y}`;
    } else if (previousY !== null && previousY !== y) {
      path += ` L ${startX} ${previousY} L ${startX} ${y}`;
    } else {
      path += ` L ${startX} ${y}`;
    }
    path += ` L ${endX} ${y}`;
    previousY = y;
  });

  return path;
}

function DigitalTrackSvg({ payload, track, width }: { payload: WaveformViewPayload; track: WaveformTrack; width: number }) {
  const path = buildDigitalPath(track, payload, width);
  return (
    <svg
      width={width}
      height={TRACK_HEIGHT}
      viewBox={`0 0 ${width} ${TRACK_HEIGHT}`}
      className="block bg-[var(--surface-strong)] text-[var(--text)]"
    >
      {path ? (
        <path d={path} fill="none" stroke="currentColor" strokeLinecap="square" strokeWidth="2" />
      ) : null}
    </svg>
  );
}

function BusTrackSvg({ payload, track, width }: { payload: WaveformViewPayload; track: WaveformTrack; width: number }) {
  const visibleSegments = track.segments
    .map((segment, index) => {
      const clipped = clipSegment(segment, payload);
      if (!clipped) {
        return null;
      }
      return {
        index,
        value: segment.value,
        start: clipped.start,
        end: clipped.end,
        startX: timeToX(payload, width, clipped.start),
        endX: timeToX(payload, width, clipped.end),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  return (
    <svg
      width={width}
      height={TRACK_HEIGHT}
      viewBox={`0 0 ${width} ${TRACK_HEIGHT}`}
      className="block bg-[var(--surface-strong)] text-[var(--text)]"
    >
      {visibleSegments.map((segment) => {
        const segmentWidth = Math.max(1, segment.endX - segment.startX);
        const skew = Math.min(10, Math.max(4, segmentWidth / 5));
        const lineStart = segment.startX + (segment.index === 0 ? 0 : skew);
        const lineEnd = segment.endX - skew;
        const textX = segment.startX + segmentWidth / 2;
        return (
          <g key={`${track.signalId}-${segment.index}`}>
            <line x1={lineStart} y1={BUS_TOP_Y} x2={lineEnd} y2={BUS_TOP_Y} stroke="currentColor" strokeWidth="2" />
            <line x1={lineStart} y1={BUS_BOTTOM_Y} x2={lineEnd} y2={BUS_BOTTOM_Y} stroke="currentColor" strokeWidth="2" />
            {segment.index === 0 ? (
              <line x1={segment.startX} y1={BUS_TOP_Y} x2={segment.startX} y2={BUS_BOTTOM_Y} stroke="currentColor" strokeOpacity="0.45" />
            ) : null}
            <text x={textX} y={BUS_MID_Y + 4} textAnchor="middle" fontSize="11" className="fill-current">
              {segment.value}
            </text>
          </g>
        );
      })}
      {visibleSegments.slice(1).map((segment) => {
        const x = segment.startX;
        const skew = 10;
        return (
          <g key={`${track.signalId}-cross-${segment.index}`} data-testid="waveform-bus-transition">
            <line x1={x - skew} y1={BUS_TOP_Y} x2={x + skew} y2={BUS_BOTTOM_Y} stroke="currentColor" strokeWidth="2" />
            <line x1={x - skew} y1={BUS_BOTTOM_Y} x2={x + skew} y2={BUS_TOP_Y} stroke="currentColor" strokeWidth="2" />
          </g>
        );
      })}
    </svg>
  );
}

function TimeAxis({ payload, width }: { payload: WaveformViewPayload; width: number }) {
  const ticks = buildTicks(payload, width);
  return (
    <svg
      width={width}
      height={AXIS_HEIGHT}
      viewBox={`0 0 ${width} ${AXIS_HEIGHT}`}
      className="block bg-[var(--surface-strong)] text-[var(--muted)]"
      data-testid="waveform-time-axis"
    >
      <line x1="0" y1="24" x2={width} y2="24" stroke="currentColor" strokeOpacity="0.6" />
      {ticks.map((time) => {
        const x = timeToX(payload, width, time);
        return (
          <g key={time}>
            <line x1={x} y1="18" x2={x} y2="30" stroke="currentColor" strokeOpacity="0.55" />
            <text x={x} y="12" textAnchor={time === payload.startTime ? "start" : time === payload.endTime ? "end" : "middle"} fontSize="11" className="fill-current">
              {time}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function WaveformTrackRow({ payload, track, width }: { payload: WaveformViewPayload; track: WaveformTrack; width: number }) {
  return (
    <>
      <div className="sticky left-0 z-10 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <div className="text-sm font-medium text-[var(--text)]">{track.label}</div>
        <div className="mt-1 text-xs text-[var(--muted)]">{track.width} bit</div>
      </div>
      <div className="border-b border-[var(--border)]">
        {isBusTrack(track) ? (
          <BusTrackSvg payload={payload} track={track} width={width} />
        ) : (
          <DigitalTrackSvg payload={payload} track={track} width={width} />
        )}
      </div>
    </>
  );
}

export function WaveformView({ title, payload }: Props) {
  const [zoomIndex, setZoomIndex] = useState(2);
  const zoom = ZOOM_STEPS[zoomIndex];
  const width = getContentWidth(payload, zoom);

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface)]">
      <header className="border-b border-[var(--border)] px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
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
          </div>
          <div className="flex items-center gap-2 text-xs text-[var(--muted)]" aria-label="横轴缩放">
            <button
              type="button"
              aria-label="缩小横轴"
              disabled={zoomIndex === 0}
              onClick={() => setZoomIndex((current) => Math.max(0, current - 1))}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-50"
            >
              -
            </button>
            <span className="min-w-16 text-center">横轴 {Math.round(zoom * 100)}%</span>
            <button
              type="button"
              aria-label="放大横轴"
              disabled={zoomIndex === ZOOM_STEPS.length - 1}
              onClick={() => setZoomIndex((current) => Math.min(ZOOM_STEPS.length - 1, current + 1))}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-50"
            >
              +
            </button>
          </div>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-auto" data-testid="waveform-scroll">
        {payload.tracks.length > 0 ? (
          <div
            className="grid min-w-max"
            style={{ gridTemplateColumns: `${LABEL_WIDTH}px ${width}px` }}
            data-testid="waveform-grid"
          >
            <div className="sticky left-0 z-20 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-xs font-medium text-[var(--muted)]">
              时间轴
            </div>
            <div className="border-b border-[var(--border)]">
              <TimeAxis payload={payload} width={width} />
            </div>
            {payload.tracks.map((track) => (
              <WaveformTrackRow key={track.signalId} payload={payload} track={track} width={width} />
            ))}
          </div>
        ) : (
          <div className="p-4 text-sm text-[var(--muted)]">无波形数据</div>
        )}
      </div>
    </section>
  );
}
