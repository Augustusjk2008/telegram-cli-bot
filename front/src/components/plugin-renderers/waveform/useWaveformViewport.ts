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
  const [windowError, setWindowError] = useState("");
  const requestIdRef = useRef(0);
  const debounceTimerRef = useRef<number | null>(null);

  useEffect(() => {
    setWindowData(initialWindow);
    setScrollTop(0);
    setScrollLeft(0);
    setWindowError("");
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
  const quantizedPixelWidth = Math.max(64, Math.ceil(visibleWaveWidth / 8) * 8);
  const quantizedWindowStart = Math.round(
    (timelineStart + (Math.min(pixelWidth, waveScrollLeft) / Math.max(1, pixelWidth)) * timelineRange) * 1000,
  ) / 1000;
  const quantizedWindowEnd = Math.round(
    (timelineStart + (Math.min(pixelWidth, waveScrollLeft + visibleWaveWidth) / Math.max(1, pixelWidth)) * timelineRange) * 1000,
  ) / 1000;
  const requestWindowStart = Math.min(quantizedWindowStart, quantizedWindowEnd);
  const requestWindowEnd = Math.max(quantizedWindowStart, quantizedWindowEnd);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    const controller = new AbortController();
    if (debounceTimerRef.current !== null) {
      window.clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    debounceTimerRef.current = window.setTimeout(() => {
      debounceTimerRef.current = null;
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      void client.queryPluginViewWindow(
        botAlias,
        pluginId,
        sessionId,
        {
          startTime: requestWindowStart,
          endTime: requestWindowEnd,
          signalIds: visibleSignalIds,
          pixelWidth: quantizedPixelWidth,
        },
        controller.signal,
      ).then((nextWindow) => {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setWindowError("");
        setWindowData(nextWindow as WaveformWindowPayload);
      }).catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        if (requestIdRef.current !== requestId) {
          return;
        }
        setWindowError(error instanceof Error ? error.message : "加载窗口失败");
      });
    }, 60);
    return () => {
      controller.abort();
      if (debounceTimerRef.current !== null) {
        window.clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
    };
  }, [botAlias, client, pluginId, quantizedPixelWidth, requestWindowEnd, requestWindowStart, sessionId, visibleSignalIds, visibleSignalsKey]);

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
    windowError,
    totalTrackCount: summary.signals.length,
    setScrollLeft,
    setScrollTop,
  };
}
