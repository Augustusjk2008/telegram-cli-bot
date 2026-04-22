import { useEffect, useRef } from "react";
import type { WaveformTrack } from "../../../services/types";

type Props = {
  track: WaveformTrack;
  width: number;
  height: number;
  startTime: number;
  endTime: number;
};

export function WaveformCanvas({ track, width, height, startTime, endTime }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

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
    const top = height * 0.28;
    const middle = height / 2;
    const bottom = height * 0.72;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "rgba(15, 23, 42, 0.92)";
    context.fillStyle = "rgba(15, 23, 42, 0.92)";
    context.lineWidth = 2;
    context.font = "11px monospace";
    for (const segment of track.segments) {
      const startX = ((segment.start - startTime) / range) * width;
      const endX = ((segment.end - startTime) / range) * width;
      context.beginPath();
      context.moveTo(startX, top);
      context.lineTo(endX, top);
      context.moveTo(startX, bottom);
      context.lineTo(endX, bottom);
      context.stroke();
      if (endX - startX >= 40) {
        context.fillText(segment.value, startX + 8, middle + 4);
      }
    }
  }, [endTime, height, startTime, track, width]);

  return <canvas ref={canvasRef} width={width} height={height} className="block bg-[var(--surface-strong)]" />;
}
