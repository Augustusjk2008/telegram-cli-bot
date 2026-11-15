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
