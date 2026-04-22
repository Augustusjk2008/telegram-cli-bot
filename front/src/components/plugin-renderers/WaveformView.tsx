import { useState } from "react";
import type {
  WaveformBusStyle,
  WaveformDisplayOptions,
  WaveformTrack,
  WaveformTrackSegment,
  WaveformViewPayload,
} from "../../services/types";

type Props = {
  title: string;
  payload: WaveformViewPayload;
};

type ResolvedWaveformDisplay = {
  defaultZoom: number;
  zoomLevels: number[];
  showTimeAxis: boolean;
  busStyle: WaveformBusStyle;
  labelWidth: number;
  minWaveWidth: number;
  pixelsPerTime: number;
  axisHeight: number;
  trackHeight: number;
};

const FALLBACK_DISPLAY: ResolvedWaveformDisplay = {
  defaultZoom: 1,
  zoomLevels: [0.5, 0.75, 1, 1.5, 2, 3, 4],
  showTimeAxis: true,
  busStyle: "cross",
  labelWidth: 220,
  minWaveWidth: 840,
  pixelsPerTime: 18,
  axisHeight: 42,
  trackHeight: 64,
};

function positiveNumber(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

function normalizeZoomLevels(value: unknown) {
  if (!Array.isArray(value)) {
    return FALLBACK_DISPLAY.zoomLevels;
  }
  const levels = value
    .filter((item): item is number => typeof item === "number" && Number.isFinite(item) && item > 0)
    .sort((left, right) => left - right);
  return levels.length > 0 ? levels : FALLBACK_DISPLAY.zoomLevels;
}

function resolveDisplay(options?: WaveformDisplayOptions): ResolvedWaveformDisplay {
  const zoomLevels = normalizeZoomLevels(options?.zoomLevels);
  return {
    defaultZoom: positiveNumber(options?.defaultZoom, FALLBACK_DISPLAY.defaultZoom),
    zoomLevels,
    showTimeAxis: options?.showTimeAxis ?? FALLBACK_DISPLAY.showTimeAxis,
    busStyle: options?.busStyle === "box" ? "box" : "cross",
    labelWidth: positiveNumber(options?.labelWidth, FALLBACK_DISPLAY.labelWidth),
    minWaveWidth: positiveNumber(options?.minWaveWidth, FALLBACK_DISPLAY.minWaveWidth),
    pixelsPerTime: positiveNumber(options?.pixelsPerTime, FALLBACK_DISPLAY.pixelsPerTime),
    axisHeight: positiveNumber(options?.axisHeight, FALLBACK_DISPLAY.axisHeight),
    trackHeight: positiveNumber(options?.trackHeight, FALLBACK_DISPLAY.trackHeight),
  };
}

function initialZoomIndex(display: ResolvedWaveformDisplay) {
  let closestIndex = 0;
  let closestDistance = Number.POSITIVE_INFINITY;
  display.zoomLevels.forEach((level, index) => {
    const distance = Math.abs(level - display.defaultZoom);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestIndex = index;
    }
  });
  return closestIndex;
}

function isBusTrack(track: WaveformTrack) {
  return track.width > 1 || track.segments.some((segment) => segment.value.length > 1);
}

function digitalLevel(value: string, display: ResolvedWaveformDisplay) {
  if (value === "1") {
    return display.trackHeight * 0.25;
  }
  if (value === "0") {
    return display.trackHeight * 0.75;
  }
  return display.trackHeight / 2;
}

function busLevels(display: ResolvedWaveformDisplay) {
  return {
    top: display.trackHeight * 0.28,
    middle: display.trackHeight / 2,
    bottom: display.trackHeight * 0.72,
  };
}

function getRange(payload: WaveformViewPayload) {
  return Math.max(1, payload.endTime - payload.startTime);
}

function getContentWidth(payload: WaveformViewPayload, zoom: number, display: ResolvedWaveformDisplay) {
  return Math.max(display.minWaveWidth, getRange(payload) * display.pixelsPerTime * zoom);
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

function buildDigitalPath(
  track: WaveformTrack,
  payload: WaveformViewPayload,
  width: number,
  display: ResolvedWaveformDisplay,
) {
  let path = "";
  let previousY: number | null = null;

  track.segments.forEach((segment) => {
    const clipped = clipSegment(segment, payload);
    if (!clipped) {
      return;
    }
    const startX = timeToX(payload, width, clipped.start);
    const endX = timeToX(payload, width, clipped.end);
    const y = digitalLevel(segment.value, display);
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

function DigitalTrackSvg({
  payload,
  track,
  width,
  display,
}: {
  payload: WaveformViewPayload;
  track: WaveformTrack;
  width: number;
  display: ResolvedWaveformDisplay;
}) {
  const path = buildDigitalPath(track, payload, width, display);
  return (
    <svg
      width={width}
      height={display.trackHeight}
      viewBox={`0 0 ${width} ${display.trackHeight}`}
      className="block bg-[var(--surface-strong)] text-[var(--text)]"
    >
      {path ? (
        <path d={path} fill="none" stroke="currentColor" strokeLinecap="square" strokeWidth="2" />
      ) : null}
    </svg>
  );
}

function BusTrackSvg({
  payload,
  track,
  width,
  display,
}: {
  payload: WaveformViewPayload;
  track: WaveformTrack;
  width: number;
  display: ResolvedWaveformDisplay;
}) {
  const levels = busLevels(display);
  const visibleSegments = track.segments
    .map((segment, index) => {
      const clipped = clipSegment(segment, payload);
      if (!clipped) {
        return null;
      }
      return {
        index,
        value: segment.value,
        startX: timeToX(payload, width, clipped.start),
        endX: timeToX(payload, width, clipped.end),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  return (
    <svg
      width={width}
      height={display.trackHeight}
      viewBox={`0 0 ${width} ${display.trackHeight}`}
      className="block bg-[var(--surface-strong)] text-[var(--text)]"
    >
      {visibleSegments.map((segment) => {
        const segmentWidth = Math.max(1, segment.endX - segment.startX);
        const skew = Math.min(10, Math.max(4, segmentWidth / 5));
        const lineStart = segment.startX + (segment.index === 0 ? 0 : skew);
        const lineEnd = Math.max(lineStart, segment.endX - skew);
        const textX = segment.startX + segmentWidth / 2;
        return (
          <g key={`${track.signalId}-${segment.index}`}>
            <line x1={lineStart} y1={levels.top} x2={lineEnd} y2={levels.top} stroke="currentColor" strokeWidth="2" />
            <line x1={lineStart} y1={levels.bottom} x2={lineEnd} y2={levels.bottom} stroke="currentColor" strokeWidth="2" />
            {segment.index === 0 ? (
              <line x1={segment.startX} y1={levels.top} x2={segment.startX} y2={levels.bottom} stroke="currentColor" strokeOpacity="0.45" />
            ) : null}
            <text x={textX} y={levels.middle + 4} textAnchor="middle" fontSize="11" className="fill-current">
              {segment.value}
            </text>
          </g>
        );
      })}
      {display.busStyle === "cross" ? visibleSegments.slice(1).map((segment) => {
        const x = segment.startX;
        const skew = 10;
        return (
          <g key={`${track.signalId}-cross-${segment.index}`} data-testid="waveform-bus-transition">
            <line x1={x - skew} y1={levels.top} x2={x + skew} y2={levels.bottom} stroke="currentColor" strokeWidth="2" />
            <line x1={x - skew} y1={levels.bottom} x2={x + skew} y2={levels.top} stroke="currentColor" strokeWidth="2" />
          </g>
        );
      }) : null}
    </svg>
  );
}

function TimeAxis({
  payload,
  width,
  display,
}: {
  payload: WaveformViewPayload;
  width: number;
  display: ResolvedWaveformDisplay;
}) {
  const ticks = buildTicks(payload, width);
  const axisY = display.axisHeight * 0.58;
  return (
    <svg
      width={width}
      height={display.axisHeight}
      viewBox={`0 0 ${width} ${display.axisHeight}`}
      className="block bg-[var(--surface-strong)] text-[var(--muted)]"
      data-testid="waveform-time-axis"
    >
      <line x1="0" y1={axisY} x2={width} y2={axisY} stroke="currentColor" strokeOpacity="0.6" />
      {ticks.map((time) => {
        const x = timeToX(payload, width, time);
        return (
          <g key={time}>
            <line x1={x} y1={axisY - 6} x2={x} y2={axisY + 6} stroke="currentColor" strokeOpacity="0.55" />
            <text x={x} y={Math.max(12, axisY - 12)} textAnchor={time === payload.startTime ? "start" : time === payload.endTime ? "end" : "middle"} fontSize="11" className="fill-current">
              {time}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function WaveformTrackRow({
  payload,
  track,
  width,
  display,
}: {
  payload: WaveformViewPayload;
  track: WaveformTrack;
  width: number;
  display: ResolvedWaveformDisplay;
}) {
  return (
    <>
      <div className="sticky left-0 z-10 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <div className="text-sm font-medium text-[var(--text)]">{track.label}</div>
        <div className="mt-1 text-xs text-[var(--muted)]">{track.width} bit</div>
      </div>
      <div className="border-b border-[var(--border)]">
        {isBusTrack(track) ? (
          <BusTrackSvg payload={payload} track={track} width={width} display={display} />
        ) : (
          <DigitalTrackSvg payload={payload} track={track} width={width} display={display} />
        )}
      </div>
    </>
  );
}

export function WaveformView({ title, payload }: Props) {
  const display = resolveDisplay(payload.display);
  const [zoomIndex, setZoomIndex] = useState(() => initialZoomIndex(display));
  const safeZoomIndex = Math.min(display.zoomLevels.length - 1, Math.max(0, zoomIndex));
  const zoom = display.zoomLevels[safeZoomIndex] || display.defaultZoom;
  const width = getContentWidth(payload, zoom, display);

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
              disabled={safeZoomIndex === 0}
              onClick={() => setZoomIndex((current) => Math.max(0, current - 1))}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-50"
            >
              -
            </button>
            <span className="min-w-16 text-center">横轴 {Math.round(zoom * 100)}%</span>
            <button
              type="button"
              aria-label="放大横轴"
              disabled={safeZoomIndex === display.zoomLevels.length - 1}
              onClick={() => setZoomIndex((current) => Math.min(display.zoomLevels.length - 1, current + 1))}
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
            style={{ gridTemplateColumns: `${display.labelWidth}px ${width}px` }}
            data-testid="waveform-grid"
          >
            {display.showTimeAxis ? (
              <>
                <div className="sticky left-0 z-20 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-xs font-medium text-[var(--muted)]">
                  时间轴
                </div>
                <div className="border-b border-[var(--border)]">
                  <TimeAxis payload={payload} width={width} display={display} />
                </div>
              </>
            ) : null}
            {payload.tracks.map((track) => (
              <WaveformTrackRow key={track.signalId} payload={payload} track={track} width={width} display={display} />
            ))}
          </div>
        ) : (
          <div className="p-4 text-sm text-[var(--muted)]">无波形数据</div>
        )}
      </div>
    </section>
  );
}
