import { useEffect, useMemo, useRef } from "react";
import type { WaveformTrack, WaveformTrackSegment } from "../../../services/types";
import { getDenseSegmentLayout } from "./denseSegmentLayout";

type Props = {
  track: WaveformTrack;
  width: number;
  height: number;
  startTime: number;
  endTime: number;
  formatValue?: (track: WaveformTrack, value: string) => string;
};

export function WaveformCanvas({ track, width, height, startTime, endTime, formatValue }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const isDigitalCanvas = track.width === 1;
  const denseSegments = useMemo(
    () => track.segments.filter((segment) => (
      segment.kind === "dense" || segment.value === "mixed" || (segment.transitionCount ?? 0) > 0
    )),
    [track.segments],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    if (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent)) {
      return;
    }
    let context: CanvasRenderingContext2D | null = null;
    try {
      context = canvas.getContext("2d");
    } catch {
      return;
    }
    if (!context) {
      return;
    }
    const range = Math.max(1, endTime - startTime);
    const denseLayout = getDenseSegmentLayout(height);
    const top = denseLayout.bandTop;
    const middle = denseLayout.middleY;
    const bottom = denseLayout.bandBottom;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "rgba(15, 23, 42, 0.92)";
    context.fillStyle = "rgba(15, 23, 42, 0.92)";
    context.lineWidth = 2;
    context.font = "11px monospace";
    let previousLevel: number | null = null;
    const drawDenseSegment = (segment: WaveformTrackSegment, startX: number, endX: number) => {
      const segmentWidth = Math.max(1, endX - startX);
      context.globalAlpha = 0.12;
      context.fillRect(startX, top, segmentWidth, bottom - top);
      context.globalAlpha = 0.75;
      context.beginPath();
      context.moveTo(startX, top);
      context.lineTo(endX, bottom);
      context.moveTo(startX, bottom);
      context.lineTo(endX, top);
      context.stroke();
      context.globalAlpha = 1;
      if (segmentWidth >= 56 && segment.transitionCount) {
        context.save();
        context.textAlign = "center";
        context.fillText(`${segment.transitionCount} changes`, startX + segmentWidth / 2, denseLayout.labelY);
        context.restore();
      }
    };
    for (const segment of track.segments) {
      const startX = ((segment.start - startTime) / range) * width;
      const endX = ((segment.end - startTime) / range) * width;
      if (segment.kind === "dense" || segment.value === "mixed" || (segment.transitionCount ?? 0) > 0) {
        drawDenseSegment(segment, startX, endX);
        continue;
      }
      if (isDigitalCanvas) {
        const level = segment.value === "1" ? top : segment.value === "0" ? bottom : middle;
        context.beginPath();
        if (previousLevel === null) {
          context.moveTo(startX, level);
        } else {
          context.moveTo(startX, previousLevel);
          context.lineTo(startX, level);
        }
        context.lineTo(endX, level);
        context.stroke();
        previousLevel = level;
        continue;
      }
      context.beginPath();
      context.moveTo(startX, top);
      context.lineTo(endX, top);
      context.moveTo(startX, bottom);
      context.lineTo(endX, bottom);
      context.stroke();
      if (endX - startX >= 40) {
        context.fillText(formatValue ? formatValue(track, segment.value) : segment.value, startX + 8, middle + 4);
      }
    }
  }, [denseSegments, endTime, formatValue, height, isDigitalCanvas, startTime, track, width]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      data-testid={isDigitalCanvas ? "waveform-digital-canvas" : "waveform-bus-canvas"}
      className="block bg-[var(--surface-strong)]"
    />
  );
}
