import { useCallback, useEffect, useMemo, useState } from "react";
import type { HostEffect, WaveformBusStyle, WaveformDisplayOptions, WaveformSignalSummary, WaveformTrack, WaveformTrackSegment, WaveformViewSummary, WaveformWindowPayload, WaveformInspectPayload } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { WaveformCanvas } from "./waveform/WaveformCanvas";
import { getDenseSegmentLayout } from "./waveform/denseSegmentLayout";
import { DEFAULT_WAVEFORM_RADIX, WAVEFORM_RADIX_OPTIONS, formatWaveformValue, type WaveformRadix } from "./waveform/radix";
import { useWaveformViewport } from "./waveform/useWaveformViewport";
import { WaveformSignalNavigator } from "./waveform/WaveformSignalNavigator";
import { WaveformStatusPanel } from "./waveform/WaveformStatusPanel";
import { WaveformTimelineNavigator } from "./waveform/WaveformTimelineNavigator";
import { clampTime, fitAllRange, fitSignalsRange, rangeToContentWidth, timeToX, xToTime, zoomRange, type TimeRange } from "./waveform/timelineMath";
import "./waveform/waveform.css";

type Props = {
  title: string;
  botAlias: string;
  client: WebBotClient;
  pluginId: string;
  sessionId?: string;
  summary: WaveformViewSummary;
  initialWindow: WaveformWindowPayload;
  onApplyHostEffects?: (effects: HostEffect[], pluginId?: string) => Promise<void> | void;
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

function resolveDisplay(options?: WaveformDisplayOptions): ResolvedWaveformDisplay {
  const levels = Array.isArray(options?.zoomLevels)
    ? options.zoomLevels.filter((level): level is number => typeof level === "number" && Number.isFinite(level) && level > 0).sort((a, b) => a - b)
    : [];
  return {
    defaultZoom: positiveNumber(options?.defaultZoom, FALLBACK_DISPLAY.defaultZoom),
    zoomLevels: levels.length ? levels : FALLBACK_DISPLAY.zoomLevels,
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
  return display.zoomLevels.reduce((best, level, index) => Math.abs(level - display.defaultZoom) < Math.abs(display.zoomLevels[best] - display.defaultZoom) ? index : best, 0);
}

function clipSegment(segment: WaveformTrackSegment, startTime: number, endTime: number) {
  const start = Math.max(startTime, segment.start);
  const end = Math.min(endTime, Math.max(start, segment.end));
  return end > start ? { start, end } : null;
}

function isDenseSegment(segment: Pick<WaveformTrackSegment, "kind" | "transitionCount" | "value">) {
  return segment.kind === "dense" || segment.value === "mixed" || (segment.transitionCount ?? 0) > 0;
}

function digitalLevel(value: string, height: number) {
  return value === "1" ? height * 0.25 : value === "0" ? height * 0.75 : height / 2;
}

function busLevels(height: number) {
  return { top: height * 0.28, middle: height / 2, bottom: height * 0.72 };
}

function buildDigitalPath(track: WaveformTrack, startTime: number, endTime: number, width: number, height: number) {
  let path = "";
  let previousY: number | null = null;
  for (const segment of track.segments) {
    const clipped = clipSegment(segment, startTime, endTime);
    if (!clipped) continue;
    const startX = timeToX(startTime, endTime, width, clipped.start);
    const endX = timeToX(startTime, endTime, width, clipped.end);
    const y = digitalLevel(segment.value, height);
    if (!path) path = `M ${startX} ${y}`;
    else if (previousY !== y) path += ` L ${startX} ${previousY} L ${startX} ${y}`;
    else path += ` L ${startX} ${y}`;
    path += ` L ${endX} ${y}`;
    previousY = y;
  }
  return path;
}

function DigitalTrackSvg({ track, startTime, endTime, width, height }: { track: WaveformTrack; startTime: number; endTime: number; width: number; height: number }) {
  const path = buildDigitalPath(track, startTime, endTime, width, height);
  const denseLayout = getDenseSegmentLayout(height);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block bg-[var(--surface-strong)]" data-testid="waveform-digital-svg">
      {path ? <path d={path} fill="none" stroke="var(--waveform-line)" strokeLinecap="square" strokeWidth="2" /> : null}
      {track.segments.map((segment, index) => {
        const clipped = clipSegment(segment, startTime, endTime);
        if (!clipped || !isDenseSegment(segment)) return null;
        const startX = timeToX(startTime, endTime, width, clipped.start);
        const endX = timeToX(startTime, endTime, width, clipped.end);
        return (
          <g key={`${track.signalId}-dense-${index}`} data-testid="waveform-dense-segment">
            <rect x={startX} y={denseLayout.bandTop} width={Math.max(1, endX - startX)} height={denseLayout.bandBottom - denseLayout.bandTop} fill="var(--waveform-dense-fill)" opacity="0.18" />
            <line x1={startX} y1={denseLayout.bandTop} x2={endX} y2={denseLayout.bandBottom} stroke="var(--waveform-dense-line)" opacity="0.8" />
            <line x1={startX} y1={denseLayout.bandBottom} x2={endX} y2={denseLayout.bandTop} stroke="var(--waveform-dense-line)" opacity="0.8" />
            {(segment.transitionCount ?? 0) > 0 && endX - startX >= 48 ? <text x={(startX + endX) / 2} y={denseLayout.labelY} textAnchor="middle" fontSize="11" fill="var(--waveform-text)">{segment.transitionCount} changes</text> : null}
          </g>
        );
      })}
    </svg>
  );
}

function BusTrackSvg({ track, startTime, endTime, width, height, busStyle, formatValue }: { track: WaveformTrack; startTime: number; endTime: number; width: number; height: number; busStyle: WaveformBusStyle; formatValue: (value: string) => string }) {
  const levels = busLevels(height);
  const denseLayout = getDenseSegmentLayout(height);
  const segments = track.segments.map((segment, index) => {
    const clipped = clipSegment(segment, startTime, endTime);
    if (!clipped) return null;
    return { segment, index, startX: timeToX(startTime, endTime, width, clipped.start), endX: timeToX(startTime, endTime, width, clipped.end) };
  }).filter((item): item is NonNullable<typeof item> => item !== null);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block bg-[var(--surface-strong)]" data-testid="waveform-bus-svg">
      {segments.map(({ segment, index, startX, endX }) => {
        const segmentWidth = Math.max(1, endX - startX);
        if (isDenseSegment(segment)) {
          return <g key={`${track.signalId}-${index}`} data-testid="waveform-dense-segment"><rect x={startX} y={denseLayout.bandTop} width={segmentWidth} height={denseLayout.bandBottom - denseLayout.bandTop} fill="var(--waveform-dense-fill)" opacity="0.18" /><line x1={startX} y1={denseLayout.bandTop} x2={endX} y2={denseLayout.bandBottom} stroke="var(--waveform-dense-line)" /><line x1={startX} y1={denseLayout.bandBottom} x2={endX} y2={denseLayout.bandTop} stroke="var(--waveform-dense-line)" />{segmentWidth >= 48 ? <text x={(startX + endX) / 2} y={denseLayout.labelY} textAnchor="middle" fontSize="11" fill="var(--waveform-text)">{segment.transitionCount ? `${segment.transitionCount} changes` : "变化"}</text> : null}</g>;
        }
        const skew = Math.min(10, Math.max(4, segmentWidth / 5));
        return <g key={`${track.signalId}-${index}`}><line x1={startX + (index ? skew : 0)} y1={levels.top} x2={Math.max(startX, endX - skew)} y2={levels.top} stroke="var(--waveform-line)" strokeWidth="2" /><line x1={startX + (index ? skew : 0)} y1={levels.bottom} x2={Math.max(startX, endX - skew)} y2={levels.bottom} stroke="var(--waveform-line)" strokeWidth="2" /><text x={(startX + endX) / 2} y={levels.middle + 4} textAnchor="middle" fontSize="11" fill="var(--waveform-text)">{formatValue(segment.value)}</text></g>;
      })}
      {busStyle === "cross" ? segments.slice(1).map(({ index, startX }) => <g key={`${track.signalId}-cross-${index}`} data-testid="waveform-bus-transition"><line x1={startX - 10} y1={levels.top} x2={startX + 10} y2={levels.bottom} stroke="var(--waveform-line)" /><line x1={startX - 10} y1={levels.bottom} x2={startX + 10} y2={levels.top} stroke="var(--waveform-line)" /></g>) : null}
    </svg>
  );
}

function buildTicks(startTime: number, endTime: number, width: number) {
  const range = Math.max(1, endTime - startTime);
  const target = Math.max(2, Math.floor(width / 96));
  const raw = range / target;
  const exponent = Math.floor(Math.log10(Math.max(1, raw)));
  const base = 10 ** exponent;
  const fraction = raw / base;
  const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * base;
  const ticks: number[] = [startTime];
  for (let time = Math.ceil(startTime / step) * step; time < endTime; time += step) if (time > startTime) ticks.push(time);
  if (endTime !== startTime) ticks.push(endTime);
  return ticks;
}

function TimeAxis({ startTime, endTime, width, height }: { startTime: number; endTime: number; width: number; height: number }) {
  const axisY = height * 0.58;
  return <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block bg-[var(--surface-strong)]" data-testid="waveform-time-axis"><line x1="0" y1={axisY} x2={width} y2={axisY} stroke="var(--waveform-line)" opacity="0.6" />{buildTicks(startTime, endTime, width).map((time) => { const x = timeToX(startTime, endTime, width, time); return <g key={time}><line x1={x} y1={axisY - 6} x2={x} y2={axisY + 6} stroke="var(--waveform-line)" opacity="0.55" /><text x={x} y={Math.max(12, axisY - 12)} textAnchor={time === startTime ? "start" : time === endTime ? "end" : "middle"} fontSize="11" fill="var(--waveform-text)">{time}</text></g>; })}</svg>;
}

function WaveformTrackRow({ track, startTime, endTime, width, display, radix, onRadixChange, formatValue }: { track: WaveformTrack; startTime: number; endTime: number; width: number; display: ResolvedWaveformDisplay; radix: WaveformRadix; onRadixChange: (signalId: string, radix: WaveformRadix) => void; formatValue: (track: WaveformTrack, value: string) => string }) {
  const useCanvas = track.segments.length > 400;
  return <><div className="sticky left-0 z-10 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2"><div className="min-w-0 truncate text-sm font-medium text-[var(--text)]">{track.label}</div><div className="mt-1 flex items-center gap-2 text-xs text-[var(--muted)]"><span>{track.width} bit</span>{track.width > 1 ? <select aria-label={`${track.label} 显示进制`} value={radix} onChange={(event) => onRadixChange(track.signalId, event.currentTarget.value as WaveformRadix)} className="h-6 rounded border border-[var(--border)] bg-[var(--surface-strong)] px-1 text-xs text-[var(--text)]">{WAVEFORM_RADIX_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : null}</div></div><div className="border-b border-[var(--border)]">{useCanvas ? <WaveformCanvas track={track} width={width} height={display.trackHeight} startTime={startTime} endTime={endTime} formatValue={formatValue} /> : track.width > 1 ? <BusTrackSvg track={track} startTime={startTime} endTime={endTime} width={width} height={display.trackHeight} busStyle={display.busStyle} formatValue={(value) => formatValue(track, value)} /> : <DigitalTrackSvg track={track} startTime={startTime} endTime={endTime} width={width} height={display.trackHeight} />}</div></>;
}

function initialExpandedScopes(signals: WaveformSignalSummary[]) {
  const scopes = new Set<string>();
  for (const signal of signals) {
    let path = "";
    for (const part of signal.scopeParts || signal.label.split(".").slice(0, -1)) {
      path = path ? `${path}.${part}` : part;
      scopes.add(path);
    }
  }
  return Array.from(scopes);
}

export function WaveformView({ title, botAlias, client, pluginId, sessionId, summary, initialWindow, onApplyHostEffects }: Props) {
  const display = resolveDisplay(summary.display);
  const fullRange = useMemo(() => fitAllRange(summary.startTime, summary.endTime), [summary.endTime, summary.startTime]);
  const [viewRange, setViewRange] = useState<TimeRange>(fullRange);
  const [zoomIndex, setZoomIndex] = useState(() => initialZoomIndex(display));
  const [selectedSignalIds, setSelectedSignalIds] = useState<string[]>(() => summary.defaultSignalIds.filter((id) => summary.signals.some((signal) => signal.signalId === id)));
  const [favoriteSignalIds, setFavoriteSignalIds] = useState<string[]>([]);
  const [expandedScopes, setExpandedScopes] = useState<string[]>(() => initialExpandedScopes(summary.signals));
  const [radixBySignalId, setRadixBySignalId] = useState<Record<string, WaveformRadix>>({});
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [cursorTime, setCursorTime] = useState<number | null>(null);
  const [measureStartTime, setMeasureStartTime] = useState<number | null>(null);
  const [measureEndTime, setMeasureEndTime] = useState<number | null>(null);
  const [inspect, setInspect] = useState<WaveformInspectPayload | null>(null);
  const [inspectError, setInspectError] = useState("");
  const [isInspecting, setIsInspecting] = useState(false);
  const safeZoomIndex = Math.min(display.zoomLevels.length - 1, Math.max(0, zoomIndex));
  const zoom = display.zoomLevels[safeZoomIndex] || display.defaultZoom;
  const isFullRange = viewRange.startTime === fullRange.startTime && viewRange.endTime === fullRange.endTime;
  const width = isFullRange ? display.minWaveWidth : rangeToContentWidth(viewRange.startTime, viewRange.endTime, display.pixelsPerTime, zoom, display.minWaveWidth);
  const selectedSet = useMemo(() => new Set(selectedSignalIds), [selectedSignalIds]);
  const selectedSignals = useMemo(() => summary.signals.filter((signal) => selectedSet.has(signal.signalId)), [selectedSet, summary.signals]);
  const formatTrackValue = useCallback((track: WaveformTrack, value: string) => formatWaveformValue(value, track.width, radixBySignalId[track.signalId] || (track.width > 1 ? "unsigned-hex" : DEFAULT_WAVEFORM_RADIX)), [radixBySignalId]);
  const toggleSignal = useCallback((signalId: string) => setSelectedSignalIds((current) => current.includes(signalId) ? current.filter((id) => id !== signalId) : [...current, signalId]), []);
  const toggleFavorite = useCallback((signalId: string) => setFavoriteSignalIds((current) => current.includes(signalId) ? current.filter((id) => id !== signalId) : [...current, signalId]), []);
  const toggleScope = useCallback((scopeId: string) => setExpandedScopes((current) => current.includes(scopeId) ? current.filter((id) => id !== scopeId) : [...current, scopeId]), []);
  const handleRangeChange = useCallback((next: TimeRange) => {
    const startTime = clampTime(Math.min(next.startTime, next.endTime - 1), fullRange.startTime, fullRange.endTime - 1);
    const endTime = clampTime(Math.max(next.endTime, startTime + 1), startTime + 1, fullRange.endTime);
    setViewRange({ startTime, endTime });
  }, [fullRange.endTime, fullRange.startTime]);
  const zoomBy = useCallback((factor: number) => {
    const next = zoomRange(viewRange, fullRange, factor);
    handleRangeChange(next);
    setZoomIndex((current) => factor > 1 ? Math.min(display.zoomLevels.length - 1, current + 1) : Math.max(0, current - 1));
  }, [display.zoomLevels.length, fullRange, handleRangeChange, viewRange]);
  const { viewportRef, visibleTracks, firstTrackIndex, rowHeight, windowError, totalTrackCount, setScrollLeft, setScrollTop, isLoading } = useWaveformViewport({ botAlias, client, pluginId, sessionId, summary, initialWindow, signals: selectedSignals, viewStartTime: viewRange.startTime, viewEndTime: viewRange.endTime, display, pixelWidth: width });
  const beforeSpacerHeight = firstTrackIndex * rowHeight;
  const afterSpacerHeight = Math.max(0, totalTrackCount - firstTrackIndex - visibleTracks.length) * rowHeight;
  const dense = visibleTracks.some((track) => track.segments.some(isDenseSegment));
  const activeTime = cursorTime ?? hoverTime;
  const delta = measureStartTime != null && measureEndTime != null ? Math.abs(measureEndTime - measureStartTime) : null;

  useEffect(() => {
    setViewRange(fullRange);
    setSelectedSignalIds(summary.defaultSignalIds.filter((id) => summary.signals.some((signal) => signal.signalId === id)));
    setExpandedScopes(initialExpandedScopes(summary.signals));
    setCursorTime(null);
    setMeasureStartTime(null);
    setMeasureEndTime(null);
    setInspect(null);
  }, [fullRange, summary.defaultSignalIds, summary.path, summary.signals]);

  const inspectCursor = useCallback(async () => {
    if (cursorTime == null || !sessionId || selectedSignalIds.length === 0) return;
    setIsInspecting(true);
    setInspectError("");
    try {
      const result = await client.queryPluginViewWindow(botAlias, pluginId, sessionId, { op: "inspect", time: cursorTime, signalIds: selectedSignalIds }) as WaveformInspectPayload;
      setInspect(result);
    } catch (error) {
      setInspectError(error instanceof Error ? error.message : "精确查询失败");
    } finally {
      setIsInspecting(false);
    }
  }, [botAlias, client, cursorTime, pluginId, selectedSignalIds, sessionId]);

  const copyValue = useCallback((value: string | null) => {
    if (value == null) return;
    const effect: HostEffect = { type: "copy_text", text: value };
    if (onApplyHostEffects) void onApplyHostEffects([effect], pluginId);
    else void navigator.clipboard?.writeText(value);
  }, [onApplyHostEffects, pluginId]);

  const openLogLine = useCallback((line: number) => {
    const logPath = summary.log?.logPath;
    if (logPath && onApplyHostEffects) void onApplyHostEffects([{ type: "open_file", path: logPath, line }], pluginId);
  }, [onApplyHostEffects, pluginId, summary.log?.logPath]);

  const jumpToSimulationTime = useCallback((time: number) => {
    const clamped = clampTime(time, fullRange.startTime, fullRange.endTime);
    const currentLength = Math.max(1, viewRange.endTime - viewRange.startTime);
    const nextLength = Math.min(currentLength, Math.max(1, fullRange.endTime - fullRange.startTime));
    const startTime = clampTime(clamped - nextLength / 2, fullRange.startTime, fullRange.endTime - nextLength);
    setViewRange({ startTime, endTime: Math.min(fullRange.endTime, startTime + nextLength) });
    setCursorTime(clamped);
    setMeasureStartTime(null);
    setMeasureEndTime(null);
    setInspect(null);
  }, [fullRange.endTime, fullRange.startTime, viewRange.endTime, viewRange.startTime]);

  const handleStageMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left - display.labelWidth;
    setHoverTime(x >= 0 ? xToTime(viewRange.startTime, viewRange.endTime, width, x) : null);
  };
  const handleStageClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left - display.labelWidth;
    if (x < 0) return;
    const time = xToTime(viewRange.startTime, viewRange.endTime, width, x);
    if (cursorTime == null || measureEndTime != null) {
      setCursorTime(time); setMeasureStartTime(null); setMeasureEndTime(null); setInspect(null);
    } else {
      setMeasureStartTime(cursorTime); setMeasureEndTime(time); setCursorTime(time); setInspect(null);
    }
  };

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface)]" data-waveform>
      <header className="border-b border-[var(--border)] px-3 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0"><h2 className="truncate text-base font-semibold text-[var(--text)]">{title}</h2><p className="truncate text-xs text-[var(--muted)]">{summary.path} · {summary.timescale} · {summary.startTime} - {summary.endTime}</p></div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]"><span>{hoverTime != null ? `悬停 ${Math.round(hoverTime * 1000) / 1000}` : "移动到波形查看时间"}</span>{delta != null ? <strong className="text-[var(--accent)]">Δt {delta}</strong> : null}<button type="button" onClick={() => zoomBy(0.5)} disabled={isFullRange} aria-label="缩小横轴" className="rounded border border-[var(--border)] px-2 py-1 text-[var(--text)] disabled:opacity-50">−</button><span>{Math.round(zoom * 100)}%</span><button type="button" onClick={() => zoomBy(2)} aria-label="放大横轴" className="rounded border border-[var(--border)] px-2 py-1 text-[var(--text)]">+</button><button type="button" onClick={() => void inspectCursor()} disabled={cursorTime == null || !sessionId || isInspecting} className="rounded border border-[var(--border)] px-2 py-1 text-[var(--text)] disabled:opacity-50">{isInspecting ? "查询中…" : "精确查询"}</button></div>
        </div>
        {activeTime != null ? <div className="mt-1 text-xs text-[var(--muted)]">游标 {Math.round(activeTime * 1000) / 1000}{delta != null ? ` · Δt ${delta}` : ""}</div> : null}
      </header>
      <WaveformTimelineNavigator fullRange={fullRange} viewRange={viewRange} overview={summary.overview} onRangeChange={handleRangeChange} onFitAll={() => setViewRange(fullRange)} onFitSelected={() => handleRangeChange(fitSignalsRange(selectedSignals, fullRange))} onStart={() => handleRangeChange({ startTime: fullRange.startTime, endTime: Math.min(fullRange.endTime, fullRange.startTime + Math.max(1, viewRange.endTime - viewRange.startTime)) })} onEnd={() => { const length = Math.max(1, viewRange.endTime - viewRange.startTime); handleRangeChange({ startTime: Math.max(fullRange.startTime, fullRange.endTime - length), endTime: fullRange.endTime }); }} />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(190px,240px)_minmax(0,1fr)] max-[700px]:grid-cols-[minmax(150px,38vw)_minmax(0,1fr)]">
        <WaveformSignalNavigator signals={summary.signals} selectedSignalIds={selectedSignalIds} favoriteSignalIds={favoriteSignalIds} expandedScopes={expandedScopes} onToggleSignal={toggleSignal} onToggleFavorite={toggleFavorite} onToggleScope={toggleScope} />
        <div ref={viewportRef} className="relative min-h-0 overflow-auto" data-testid="waveform-scroll" onScroll={(event) => { setScrollLeft(event.currentTarget.scrollLeft); setScrollTop(Math.max(0, event.currentTarget.scrollTop - (display.showTimeAxis ? display.axisHeight : 0))); }}>
          {windowError ? <div className="sticky top-0 z-40 border-b border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-3 py-2 text-xs text-[var(--danger)]">{windowError}</div> : null}
          <div className="relative min-w-max" data-testid="waveform-stage" onMouseMove={handleStageMove} onMouseLeave={() => setHoverTime(null)} onClick={handleStageClick}>
            {display.showTimeAxis ? <div className="sticky top-0 z-20 grid min-w-max border-b border-[var(--border)]" style={{ gridTemplateColumns: `${display.labelWidth}px ${width}px` }}><div className="sticky left-0 z-20 bg-[var(--surface)] px-3 py-3 text-xs font-medium text-[var(--muted)]">时间轴</div><TimeAxis startTime={viewRange.startTime} endTime={viewRange.endTime} width={width} height={display.axisHeight} /></div> : null}
            {selectedSignals.length ? <><div style={{ height: beforeSpacerHeight }} /><div className="grid min-w-max" style={{ gridTemplateColumns: `${display.labelWidth}px ${width}px` }} data-testid="waveform-grid">{visibleTracks.map((track) => <WaveformTrackRow key={track.signalId} track={track} startTime={viewRange.startTime} endTime={viewRange.endTime} width={width} display={display} radix={radixBySignalId[track.signalId] || (track.width > 1 ? "unsigned-hex" : DEFAULT_WAVEFORM_RADIX)} onRadixChange={(signalId, radix) => setRadixBySignalId((current) => ({ ...current, [signalId]: radix }))} formatValue={formatTrackValue} />)}</div><div style={{ height: afterSpacerHeight }} /></> : <div className="p-4 text-sm text-[var(--muted)]">请在左侧选择要加载的信号</div>}
            {activeTime != null ? <div className="pointer-events-none absolute top-0 z-30 h-full border-l-2 border-[var(--accent)]" style={{ left: display.labelWidth + timeToX(viewRange.startTime, viewRange.endTime, width, activeTime) }} data-testid="waveform-cursor" /> : null}
          </div>
        </div>
      </div>
      {inspect ? <div className="max-h-28 overflow-auto border-t border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs" data-testid="waveform-inspect-panel"><div className="mb-1 font-medium text-[var(--text)]">精确值 · {inspect.time}</div><div className="flex flex-wrap gap-2">{inspect.values.map((item) => { const signal = summary.signals.find((candidate) => candidate.signalId === item.signalId); const value = item.value == null ? "—" : formatWaveformValue(item.value, signal?.width || 1, radixBySignalId[item.signalId] || ((signal?.width || 1) > 1 ? "unsigned-hex" : DEFAULT_WAVEFORM_RADIX)); return <span key={item.signalId} className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1"><span>{signal?.label || item.signalId}: {value}</span>{item.value != null ? <button type="button" onClick={() => copyValue(value)} className="text-[var(--accent)]">复制</button> : null}</span>; })}</div></div> : null}
      {inspectError ? <div className="border-t border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-3 py-2 text-xs text-[var(--danger)]">{inspectError}</div> : null}
      <WaveformStatusPanel summary={summary} loading={isLoading} dense={dense} onOpenLogLine={openLogLine} onJumpToTime={jumpToSimulationTime} />
    </section>
  );
}
