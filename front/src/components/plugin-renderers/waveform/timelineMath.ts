export type TimeRange = { startTime: number; endTime: number };

export function rangeLength(startTime: number, endTime: number) {
  return Math.max(1, endTime - startTime);
}

export function clampTime(time: number, startTime: number, endTime: number) {
  return Math.min(endTime, Math.max(startTime, time));
}

export function timeToX(startTime: number, endTime: number, width: number, time: number) {
  return ((clampTime(time, startTime, endTime) - startTime) / rangeLength(startTime, endTime)) * Math.max(0, width);
}

export function xToTime(startTime: number, endTime: number, width: number, x: number) {
  if (width <= 0) return startTime;
  return startTime + (Math.min(width, Math.max(0, x)) / width) * rangeLength(startTime, endTime);
}

export function overviewBinToX(bin: { start: number; end: number }, startTime: number, endTime: number, width: number) {
  return {
    startX: timeToX(startTime, endTime, width, bin.start),
    endX: timeToX(startTime, endTime, width, bin.end),
  };
}

export function rangeToContentWidth(
  startTime: number,
  endTime: number,
  pixelsPerTime: number,
  zoom: number,
  minWidth: number,
  maxWidth = 16000,
) {
  return Math.min(maxWidth, Math.max(minWidth, rangeLength(startTime, endTime) * Math.max(0.01, pixelsPerTime) * Math.max(0.01, zoom)));
}

export function zoomRange(
  current: TimeRange,
  full: TimeRange,
  factor: number,
  anchor = (current.startTime + current.endTime) / 2,
): TimeRange {
  const nextLength = Math.min(rangeLength(full.startTime, full.endTime), Math.max(1, rangeLength(current.startTime, current.endTime) / factor));
  const ratio = (anchor - current.startTime) / rangeLength(current.startTime, current.endTime);
  let startTime = anchor - nextLength * ratio;
  let endTime = startTime + nextLength;
  if (startTime < full.startTime) {
    startTime = full.startTime;
    endTime = startTime + nextLength;
  }
  if (endTime > full.endTime) {
    endTime = full.endTime;
    startTime = endTime - nextLength;
  }
  return { startTime, endTime };
}

export function fitAllRange(startTime: number, endTime: number): TimeRange {
  return { startTime, endTime: Math.max(startTime + 1, endTime) };
}

export function fitSignalsRange(
  signalRanges: Array<{ firstChangeTime?: number | null; lastChangeTime?: number | null }>,
  fallback: TimeRange,
): TimeRange {
  const ranges = signalRanges.filter((signal) => signal.firstChangeTime != null && signal.lastChangeTime != null);
  if (ranges.length === 0) return fallback;
  return {
    startTime: Math.min(...ranges.map((signal) => Number(signal.firstChangeTime))),
    endTime: Math.max(...ranges.map((signal) => Number(signal.lastChangeTime)), Number(fallback.startTime) + 1),
  };
}
