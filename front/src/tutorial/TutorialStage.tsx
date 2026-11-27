import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { TutorialText } from "./TutorialText";
import {
  hotspotFrameBox,
  placeCallout,
  stageTransform,
  type CalloutPlacement,
  type HotspotRect,
} from "./tutorialMotion";

type Props = {
  src: string;
  alt: string;
  hotspot?: HotspotRect;
  zoom?: number;
  /** Step number shown on the hotspot badge. */
  badge: number;
  /** Active step's title and body, drawn as a callout beside the hotspot. */
  caption?: { title: string; body: string[] };
  /** Screenshot of the following step, fetched ahead of time. */
  preloadSrc?: string;
};

/**
 * Framed screenshot. The image and the hotspot share one transformed canvas so they move together.
 * The step callout sits outside the canvas so zoom never scales its text; it is placed in frame pixels
 * next to the transformed hotspot, inside the frame.
 */
export function TutorialStage({ src, alt, hotspot, zoom, badge, caption, preloadSrc }: Props) {
  // The previous screenshot stays underneath, so the next one fades in over it instead of over an empty frame.
  const [layers, setLayers] = useState({ current: src, previous: "" });
  const [loaded, setLoaded] = useState("");
  const [aspect, setAspect] = useState(1.6);
  const [failed, setFailed] = useState("");
  if (layers.current !== src) {
    setLayers({ current: src, previous: layers.current });
  }
  const transform = stageTransform(hotspot, zoom);
  const frameRef = useRef<HTMLDivElement>(null);
  const calloutRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<(CalloutPlacement & { key: string }) | null>(null);
  const calloutKey = `${src}:${badge}`;
  const showCallout = Boolean(caption) && loaded === src;

  useEffect(() => {
    if (!preloadSrc || preloadSrc === src) {
      return;
    }
    const image = new Image();
    image.src = preloadSrc;
  }, [preloadSrc, src]);

  // Primitive dependencies: `transform` is a new object on every render and the hotspot is tracked by its
  // coordinates. A layout effect places the callout before paint, so it never flashes at a stale position.
  const { scale, x: shiftX, y: shiftY } = transform;
  useLayoutEffect(() => {
    const frame = frameRef.current;
    const callout = calloutRef.current;
    if (!showCallout || !frame || !callout) {
      return;
    }
    const update = () => {
      // The padding box is the containing block of the absolutely positioned callout.
      const frameSize = { width: frame.clientWidth, height: frame.clientHeight };
      const calloutSize = { width: callout.offsetWidth, height: callout.offsetHeight };
      const target = hotspot ? hotspotFrameBox(hotspot, { scale, x: shiftX, y: shiftY }, frameSize) : null;
      const next = { ...placeCallout(target, frameSize, calloutSize), key: calloutKey };
      setPlacement((previous) => (
        previous && previous.key === next.key && previous.side === next.side
          && previous.left === next.left && previous.top === next.top ? previous : next
      ));
    };
    update();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(update);
    observer.observe(frame);
    observer.observe(callout);
    return () => observer.disconnect();
  }, [showCallout, calloutKey, hotspot?.x, hotspot?.y, hotspot?.w, hotspot?.h, scale, shiftX, shiftY]);

  const placed = placement?.key === calloutKey ? placement : null;

  const canvasStyle = {
    transform: `translate(${transform.x}%, ${transform.y}%) scale(${transform.scale})`,
    "--tut-zoom": transform.scale,
  } as CSSProperties;

  return (
    <figure className="tut-stage" data-testid="tutorial-stage">
      <div ref={frameRef} className="tut-stage-frame" style={{ "--tut-shot-aspect": aspect } as CSSProperties} data-zoomed={transform.scale > 1 ? "true" : "false"}>
        <div className="tut-stage-canvas" style={canvasStyle}>
          {layers.previous ? (
            <img className="tut-stage-image" src={layers.previous} alt="" aria-hidden="true" draggable={false} />
          ) : null}
          <img
            // Remount per screenshot so each one fades in. The key differs from the hotspot's: both are siblings.
            key={`image:${src}`}
            className="tut-stage-image"
            data-testid="tutorial-stage-image"
            data-loaded={loaded === src ? "true" : "false"}
            src={src}
            alt={alt}
            draggable={false}
            onLoad={({ currentTarget }) => {
              if (currentTarget.naturalHeight) setAspect(currentTarget.naturalWidth / currentTarget.naturalHeight);
              setLoaded(src);
            }}
            onError={() => setFailed(src)}
          />
          {hotspot && loaded === src ? (
            <div
              // Remount per screenshot: within one screenshot the hotspot slides, across screenshots it fades in place.
              key={`hotspot:${src}`}
              className="tut-hotspot"
              data-testid="tutorial-hotspot"
              style={{ left: `${hotspot.x}%`, top: `${hotspot.y}%`, width: `${hotspot.w}%`, height: `${hotspot.h}%` }}
              aria-hidden="true"
            >
              <span className="tut-hotspot-badge">{badge}</span>
            </div>
          ) : null}
        </div>
        {showCallout && caption ? (
          <div
            // Remount per step so each callout fades in at its own position.
            key={`callout:${calloutKey}`}
            ref={calloutRef}
            className="tut-callout"
            data-testid="tutorial-callout"
            data-side={placed?.side}
            data-placed={placed ? "true" : "false"}
            style={placed ? { left: placed.left, top: placed.top } : undefined}
            // The same text is in the step list; screen readers should not hear it twice.
            aria-hidden="true"
          >
            <p className="tut-callout-head">
              <span className="tut-callout-badge">{badge}</span>
              <span>{caption.title}</span>
            </p>
            {caption.body.map((paragraph) => (
              <p key={paragraph}><TutorialText text={paragraph} /></p>
            ))}
          </div>
        ) : null}
        {failed === src ? <p className="tut-stage-error" role="status">截图加载失败，请刷新页面后重试。</p> : null}
      </div>
    </figure>
  );
}
