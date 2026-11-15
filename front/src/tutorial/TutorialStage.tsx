import { useEffect, useState, type CSSProperties } from "react";
import { stageTransform, type HotspotRect } from "./tutorialMotion";

type Props = {
  src: string;
  alt: string;
  hotspot?: HotspotRect;
  zoom?: number;
  /** Step number shown on the hotspot badge. */
  badge: number;
  /** Screenshot of the following step, fetched ahead of time. */
  preloadSrc?: string;
};

/** Framed screenshot. The image and the hotspot share one transformed canvas so they move together. */
export function TutorialStage({ src, alt, hotspot, zoom, badge, preloadSrc }: Props) {
  // The previous screenshot stays underneath, so the next one fades in over it instead of over an empty frame.
  const [layers, setLayers] = useState({ current: src, previous: "" });
  const [loaded, setLoaded] = useState("");
  const [failed, setFailed] = useState("");
  if (layers.current !== src) {
    setLayers({ current: src, previous: layers.current });
  }
  const transform = stageTransform(hotspot, zoom);

  useEffect(() => {
    if (!preloadSrc || preloadSrc === src) {
      return;
    }
    const image = new Image();
    image.src = preloadSrc;
  }, [preloadSrc, src]);

  const canvasStyle = {
    transform: `translate(${transform.x}%, ${transform.y}%) scale(${transform.scale})`,
    "--tut-zoom": transform.scale,
  } as CSSProperties;

  return (
    <figure className="tut-stage" data-testid="tutorial-stage">
      <div className="tut-stage-frame" data-zoomed={transform.scale > 1 ? "true" : "false"}>
        <div className="tut-stage-canvas" style={canvasStyle}>
          {layers.previous ? (
            <img className="tut-stage-image" src={layers.previous} alt="" aria-hidden="true" draggable={false} />
          ) : null}
          <img
            key={src}
            className="tut-stage-image"
            data-testid="tutorial-stage-image"
            data-loaded={loaded === src ? "true" : "false"}
            src={src}
            alt={alt}
            draggable={false}
            onLoad={() => setLoaded(src)}
            onError={() => setFailed(src)}
          />
          {hotspot && loaded === src ? (
            <div
              // Remount per screenshot: within one screenshot the hotspot slides, across screenshots it fades in place.
              key={src}
              className="tut-hotspot"
              data-testid="tutorial-hotspot"
              style={{ left: `${hotspot.x}%`, top: `${hotspot.y}%`, width: `${hotspot.w}%`, height: `${hotspot.h}%` }}
              aria-hidden="true"
            >
              <span className="tut-hotspot-badge">{badge}</span>
            </div>
          ) : null}
        </div>
        {failed === src ? <p className="tut-stage-error" role="status">截图加载失败，请刷新页面后重试。</p> : null}
      </div>
    </figure>
  );
}
