import { useEffect, useMemo, useRef, useState } from "react";
import type { WebBotClient } from "../../../services/webBotClient";
import type {
  WaveformTrack,
  WaveformViewSummary,
  WaveformWindowPayload,
} from "../../../services/types";

type DisplayShape = {
  labelWidth: number;
  minWaveWidth: number;
  trackHeight: number;
};

type Props = {
  botAlias: string;
  client: WebBotClient;
  pluginId: string;
  sessionId?: string;
  summary: WaveformViewSummary;
  initialWindow: WaveformWindowPayload;
  display: DisplayShape;
  pixelWidth: number;
};

export function useWaveformViewport({
  botAlias,
  client,
  pluginId,
  sessionId,
  summary,
  initialWindow,
  display,
  pixelWidth,
}: Props) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [windowData, setWindowData] = useState(initialWindow);
  const [scrollTop, setScrollTop] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(display.trackHeight * 8);
  const [viewportWidth, setViewportWidth] = useState(display.minWaveWidth);

  useEffect(() => {
    setWindowData(initialWindow);
    setScrollTop(0);
    setScrollLeft(0);
  }, [initialWindow]);

  useEffect(() => {
    const node = viewportRef.current;
    if (!node) {
      return;
    }
    const update = () => {
      setViewportHeight(Math.max(display.trackHeight * 6, node.clientHeight || display.trackHeight * 8));
      setViewportWidth(Math.max(1, node.clientWidth || display.minWaveWidth));
    };
    update();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => update());
    observer.observe(node);
    return () => observer.disconnect();
  }, [display.minWaveWidth, display.trackHeight]);

  const rowHeight = display.trackHeight + 1;
  const visibleTrackCount = Math.max(1, Math.ceil(viewportHeight / rowHeight) + 4);
  const firstTrackIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - 2);
  const visibleSignals = useMemo(
    () => summary.signals.slice(firstTrackIndex, firstTrackIndex + visibleTrackCount),
    [firstTrackIndex, summary.signals, visibleTrackCount],
  );
  const visibleSignalIds = useMemo(
    () => visibleSignals.map((signal) => signal.signalId),
    [visibleSignals],
  );
  const visibleSignalsKey = visibleSignalIds.join("|");
  const visibleWaveWidth = Math.max(1, viewportWidth - display.labelWidth);
  const timelineStart = Number(summary.startTime);
  const timelineEnd = Number(summary.endTime);
  const timelineRange = Math.max(1, timelineEnd - timelineStart);
  const waveScrollLeft = Math.max(0, Math.min(pixelWidth, scrollLeft));
  const windowStart = timelineStart + (Math.min(pixelWidth, waveScrollLeft) / Math.max(1, pixelWidth)) * timelineRange;
  const windowEnd = timelineStart + (Math.min(pixelWidth, waveScrollLeft + visibleWaveWidth) / Math.max(1, pixelWidth)) * timelineRange;

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    const controller = new AbortController();
    void client.queryPluginViewWindow(
      botAlias,
      pluginId,
      sessionId,
      {
        startTime: windowStart,
        endTime: Math.max(windowStart, windowEnd),
        signalIds: visibleSignalIds,
        pixelWidth: Math.max(64, Math.ceil(visibleWaveWidth)),
      },
      controller.signal,
    ).then((nextWindow) => {
      setWindowData(nextWindow as WaveformWindowPayload);
    }).catch((error) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      throw error;
    });
    return () => controller.abort();
  }, [botAlias, client, pluginId, sessionId, visibleSignalsKey, visibleSignalIds, visibleWaveWidth, windowEnd, windowStart]);

  const visibleTracks = useMemo<WaveformTrack[]>(
    () =>
      visibleSignals.map((signal) => {
        const track = windowData.tracks.find((candidate) => candidate.signalId === signal.signalId);
        return track || {
          signalId: signal.signalId,
          label: signal.label,
          width: signal.width,
          segments: [],
        };
      }),
    [visibleSignals, windowData.tracks],
  );

  return {
    viewportRef,
    windowData,
    visibleTracks,
    firstTrackIndex,
    rowHeight,
    totalTrackCount: summary.signals.length,
    setScrollLeft,
    setScrollTop,
  };
}
