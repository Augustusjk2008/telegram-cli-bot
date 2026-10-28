import { useMemo, type CSSProperties } from "react";
import { useResolvedAppearance } from "./appearanceRuntime";
import type { ResolvedAppearance, ThemeIllustrationSurface } from "./types";
import { clsx } from "clsx";
import { withPublicBase } from "../utils/publicBase";

type Props = {
  surface: ThemeIllustrationSurface;
  appearance?: ResolvedAppearance;
  className?: string;
};

export function ThemeIllustrationLayer({ surface, appearance: previewAppearance, className }: Props) {
  const currentAppearance = useResolvedAppearance();
  const appearance = previewAppearance || currentAppearance;
  const illustration = appearance.illustrations;
  const visible = illustration.setId !== "none" && illustration.opacity > 0 && illustration.surfaces[surface];
  const style = useMemo(() => ({
    "--theme-illustration-opacity": String(illustration.opacity),
    "--theme-illustration-primary": illustration.colors.primary,
    "--theme-illustration-secondary": illustration.colors.secondary,
    "--theme-illustration-soft": illustration.colors.soft,
    "--theme-illustration-image": `url("${withPublicBase(illustration.resources[surface])}")`,
  }) as CSSProperties, [illustration]);
  if (!visible) return null;
  return (
    <div
      aria-hidden="true"
      data-testid={`theme-illustration-layer-${surface}`}
      data-theme-illustration-surface={surface}
      data-theme-illustration-set={illustration.setId}
      className={clsx("theme-illustration-layer", className)}
      style={{ ...style, pointerEvents: "none" }}
    >
      <div className="theme-illustration-art" />
    </div>
  );
}
