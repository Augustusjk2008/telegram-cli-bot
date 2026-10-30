import { useMemo, type CSSProperties } from "react";
import { clsx } from "clsx";
import { withPublicBase } from "../utils/publicBase";
import { useResolvedAppearance } from "./appearanceRuntime";
import { displayIllustrationLayers } from "./illustrationPresets";
import type {
  ResolvedAppearance,
  ThemeIllustrationLayerSpec,
  ThemeIllustrationLegacySurface,
  ThemeIllustrationSurface,
} from "./types";

type Props = {
  surface: ThemeIllustrationSurface | ThemeIllustrationLegacySurface;
  appearance?: ResolvedAppearance;
  className?: string;
  region?: "canvas" | "chat" | "topbar";
  zone?: "main" | "sidebar";
};

function canonicalSurface(surface: Props["surface"]): ThemeIllustrationSurface {
  if (surface === "chat" || surface === "topbar") return "workbench";
  if (surface === "management") return "agentManager";
  return surface;
}

function resourceUrl(resource: string) {
  return resource.startsWith("data:") ? resource : withPublicBase(resource);
}

function positionStyle(layer: ThemeIllustrationLayerSpec, region: Props["region"]): CSSProperties {
  const x = layer.x ?? 0;
  const y = layer.y ?? 0;
  const width = `${layer.width ?? 100}%`;
  const height = `${layer.height ?? 100}%`;
  const objectPosition = layer.objectPosition
    || (region === "topbar" ? "50% 0%" : region === "chat" ? "50% 72%" : "50% 50%");
  const base: CSSProperties = {
    inset: "auto",
    width,
    height,
    objectPosition,
    opacity: layer.opacity ?? 1,
  };
  if (layer.anchor === "center") {
    return {
      ...base,
      left: `calc(50% + ${x}%)`,
      top: `calc(50% + ${y}%)`,
      transform: "translate(-50%, -50%)",
    };
  }
  const horizontal = layer.anchor === "right" || layer.anchor === "bottom-right";
  const vertical = layer.anchor === "bottom" || layer.anchor === "bottom-left" || layer.anchor === "bottom-right";
  return {
    ...base,
    ...(horizontal ? { right: `${x}%` } : { left: `${x}%` }),
    ...(vertical ? { bottom: `${y}%` } : { top: `${y}%` }),
  };
}

function ThemeIllustrationLayerView({ surface, appearance, className, region = "canvas", zone }: Props & { appearance: ResolvedAppearance }) {
  const illustration = appearance.illustrations;
  const resolvedSurface = canonicalSurface(surface);
  const scene = illustration.scenes[resolvedSurface];
  const resources = illustration.sceneResources[resolvedSurface] || [];
  const layers = useMemo(
    () => {
      const displayed = displayIllustrationLayers(scene, resolvedSurface, resources)
        .filter((item) => item.layer.enabled && Boolean(item.resource));
      if (resolvedSurface !== "workbench" || !zone) return displayed;
      const preferredId = zone === "sidebar" ? "left-edge-foliage" : "workbench-background";
      const preferred = displayed.find((item) => item.layer.id === preferredId);
      const selected = preferred || displayed[0];
      if (!selected) return [];
      if (zone !== "sidebar") return [selected];
      return [{
        ...selected,
        layer: {
          ...selected.layer,
          anchor: "center",
          x: 0,
          y: 0,
          width: 100,
          height: 100,
          objectPosition: "0% 50%",
          opacity: 1,
        },
      }];
    },
    [resources, resolvedSurface, scene, zone],
  );
  if (illustration.opacity <= 0 || !illustration.surfaces[resolvedSurface] || layers.length === 0) return null;

  return (
    <div
      aria-hidden="true"
      data-testid={`theme-illustration-layer-${resolvedSurface}`}
      data-theme-illustration-surface={resolvedSurface}
      data-theme-illustration-region={region}
      data-theme-illustration-zone={zone}
      data-theme-illustration-count={layers.length}
      className={clsx("theme-illustration-layer", className)}
      style={{ "--theme-illustration-opacity": String(illustration.opacity), pointerEvents: "none" } as CSSProperties}
    >
      {layers.map(({ layer, index, resource }) => (
        <img
          key={layer.id}
          className="theme-illustration-art"
          data-theme-illustration-layer-id={layer.id}
          data-theme-illustration-index={index}
          data-theme-illustration-asset={layer.asset.assetId}
          src={resourceUrl(resource)}
          alt=""
          draggable={false}
          style={positionStyle(layer, region)}
        />
      ))}
    </div>
  );
}

function ConnectedThemeIllustrationLayer(props: Props) {
  const appearance = useResolvedAppearance();
  return <ThemeIllustrationLayerView {...props} appearance={appearance} />;
}

export function ThemeIllustrationLayer({ appearance: previewAppearance, ...props }: Props) {
  return previewAppearance
    ? <ThemeIllustrationLayerView {...props} appearance={previewAppearance} />
    : <ConnectedThemeIllustrationLayer {...props} />;
}
