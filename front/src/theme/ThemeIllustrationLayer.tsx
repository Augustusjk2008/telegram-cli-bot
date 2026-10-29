import { useMemo, type CSSProperties } from "react";
import { useResolvedAppearance } from "./appearanceRuntime";
import type { ResolvedAppearance, ThemeIllustrationLegacySurface, ThemeIllustrationSurface } from "./types";
import { clsx } from "clsx";
import { withPublicBase } from "../utils/publicBase";

type Props = {
  surface: ThemeIllustrationSurface | ThemeIllustrationLegacySurface;
  appearance?: ResolvedAppearance;
  className?: string;
  region?: "canvas" | "chat" | "topbar";
};

function illustrationCssImage(resource: string) {
  return `url("${resource.startsWith("data:") ? resource : withPublicBase(resource)}")`;
}

function canonicalSurface(surface: Props["surface"]): ThemeIllustrationSurface {
  if (surface === "chat" || surface === "topbar") return "workbench";
  if (surface === "management") return "agentManager";
  return surface;
}

export function ThemeIllustrationLayer({ surface, appearance: previewAppearance, className, region = "canvas" }: Props) {
  const currentAppearance = useResolvedAppearance();
  const appearance = previewAppearance || currentAppearance;
  const illustration = appearance.illustrations;
  const resolvedSurface = canonicalSurface(surface);
  const resource = illustration.resources[resolvedSurface];
  const visible = illustration.opacity > 0 && illustration.surfaces[resolvedSurface] && Boolean(resource);
  const style = useMemo(() => ({
    "--theme-illustration-opacity": String(illustration.opacity),
    "--theme-illustration-image": illustrationCssImage(resource),
    "--theme-illustration-object-position": region === "topbar" ? "50% 0%" : region === "chat" ? "50% 72%" : "50% 50%",
  }) as CSSProperties, [illustration, resource, region]);
  if (!visible) return null;
  return (
    <div
      aria-hidden="true"
      data-testid={`theme-illustration-layer-${resolvedSurface}`}
      data-theme-illustration-surface={resolvedSurface}
      data-theme-illustration-region={region}
      data-theme-illustration-asset={illustration.scenes[resolvedSurface].assetId}
      className={clsx("theme-illustration-layer", className)}
      style={{ ...style, pointerEvents: "none" }}
    >
      <img className="theme-illustration-art" src={resource.startsWith("data:") ? resource : withPublicBase(resource)} alt="" draggable={false} />
    </div>
  );
}
