/** Timings of the unfold and collapse, in milliseconds from the moment they start. */
export const TUTORIAL_TIMING = {
  scrim: 200,
  reveal: 620,
  travelDelay: 120,
  travel: 560,
  ringDelay: 400,
  ring: 600,
  contentDelay: 550,
  cardStagger: 35,
  /** The opening phase ends here; the last chapter card has landed by then. */
  openTotal: 1250,
  closeContent: 120,
  collapseDelay: 100,
  collapse: 420,
  closeTotal: 540,
  /** Reduced motion replaces both directions with one opacity cross-fade. */
  reducedFade: 160,
} as const;

export const TUTORIAL_REVEAL_EASING = "cubic-bezier(0.3, 0, 0.1, 1)";
export const TUTORIAL_COLLAPSE_EASING = "cubic-bezier(0.5, 0, 0.3, 1)";
export const TUTORIAL_TRAVEL_EASING = "cubic-bezier(0.2, 0, 0, 1)";

export type TutorialPoint = { x: number; y: number };
export type TutorialSize = { width: number; height: number };

/** Radius of the circle centred on `origin` that just covers the whole viewport. */
export function revealRadius(origin: TutorialPoint, viewport: TutorialSize): number {
  const dx = Math.max(origin.x, viewport.width - origin.x);
  const dy = Math.max(origin.y, viewport.height - origin.y);
  return Math.ceil(Math.hypot(dx, dy));
}

export function revealClipPath(radius: number, origin: TutorialPoint): string {
  return `circle(${Math.max(0, radius)}px at ${origin.x}px ${origin.y}px)`;
}

/** Hotspot rectangle in percentages of the screenshot. */
export type HotspotRect = { x: number; y: number; w: number; h: number };

export const MAX_STAGE_ZOOM = 1.8;

export type StageTransform = { scale: number; x: number; y: number };

/**
 * Transform (origin top-left, translate in percentages of the frame) that scales the canvas and brings
 * the hotspot centre towards the frame centre without ever exposing an edge of the frame.
 */
export function stageTransform(hotspot: HotspotRect | undefined, zoom: number | undefined): StageTransform {
  const requested = Number.isFinite(zoom) ? Number(zoom) : 1;
  const scale = Math.min(MAX_STAGE_ZOOM, Math.max(1, requested));
  if (!hotspot || scale === 1) {
    return { scale: 1, x: 0, y: 0 };
  }
  const minOffset = 100 - 100 * scale;
  const clampOffset = (centre: number) => {
    const offset = Math.min(0, Math.max(minOffset, 50 - scale * centre));
    return Math.round(offset * 100) / 100 || 0;
  };
  return {
    scale,
    x: clampOffset(hotspot.x + hotspot.w / 2),
    y: clampOffset(hotspot.y + hotspot.h / 2),
  };
}

export type FrameSize = { width: number; height: number };
export type FrameBox = { left: number; top: number; width: number; height: number };
export type CalloutSide = "below" | "above" | "right" | "left" | "corner";
export type CalloutPlacement = { left: number; top: number; side: CalloutSide };

export const CALLOUT_GAP = 10;
export const CALLOUT_MARGIN = 10;

/** Hotspot rectangle in frame pixels after the stage transform (canvas origin top-left, translate in % of the frame). */
export function hotspotFrameBox(hotspot: HotspotRect, transform: StageTransform, frame: FrameSize): FrameBox {
  return {
    left: (frame.width * (transform.x + transform.scale * hotspot.x)) / 100,
    top: (frame.height * (transform.y + transform.scale * hotspot.y)) / 100,
    width: (frame.width * transform.scale * hotspot.w) / 100,
    height: (frame.height * transform.scale * hotspot.h) / 100,
  };
}

function overlapArea(a: FrameBox, b: FrameBox): number {
  const width = Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left);
  const height = Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top);
  return width > 0 && height > 0 ? width * height : 0;
}

/**
 * Position for the step callout: inside the frame, beside the hotspot, covering as little of it as possible.
 * Candidates are tried below, above, right, left; ties keep that order. Without a hotspot: bottom-left corner.
 */
export function placeCallout(
  target: FrameBox | null,
  frame: FrameSize,
  size: FrameSize,
  gap = CALLOUT_GAP,
  margin = CALLOUT_MARGIN,
): CalloutPlacement {
  // A callout larger than the frame pins to the margin.
  const clampAxis = (value: number, length: number, available: number) => (
    Math.min(Math.max(value, margin), Math.max(margin, available - length - margin))
  );
  const place = (left: number, top: number, side: CalloutSide): CalloutPlacement => ({
    left: Math.round(clampAxis(left, size.width, frame.width)),
    top: Math.round(clampAxis(top, size.height, frame.height)),
    side,
  });
  if (!target) {
    return place(margin, frame.height - size.height - margin, "corner");
  }

  // Zoom can push part of a large hotspot outside the frame; only the visible part matters.
  const left = Math.max(target.left, 0);
  const top = Math.max(target.top, 0);
  const clipped = {
    left,
    top,
    width: Math.min(target.left + target.width, frame.width) - left,
    height: Math.min(target.top + target.height, frame.height) - top,
  };
  const visible = clipped.width > 0 && clipped.height > 0 ? clipped : target;

  const candidates = [
    place(target.left, target.top + target.height + gap, "below"),
    place(target.left, target.top - gap - size.height, "above"),
    place(target.left + target.width + gap, target.top, "right"),
    place(target.left - gap - size.width, target.top, "left"),
  ];
  let best = candidates[0];
  let bestOverlap = Number.POSITIVE_INFINITY;
  for (const candidate of candidates) {
    const overlap = overlapArea({ left: candidate.left, top: candidate.top, ...size }, visible);
    // Differences under half a square pixel are ties, so the candidate order decides.
    if (overlap < bestOverlap - 0.5) {
      best = candidate;
      bestOverlap = overlap;
    }
  }
  return best;
}
