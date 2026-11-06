import { useSyncExternalStore } from "react";
import { withPublicBase } from "../utils/publicBase";
import { BUILTIN_THEME, resolveAppearance, THEME_TOKENS } from "./resolveAppearance";
import { THEME_ILLUSTRATION_SURFACES } from "./illustrationPresets";
import type { ResolvedAppearance, ThemeIllustrationSurface } from "./types";

const paperAppearance = resolveAppearance(BUILTIN_THEME);
let currentAppearance = paperAppearance;
const listeners = new Set<() => void>();

function illustrationCssImage(resource: string) {
  return `url("${resource.startsWith("data:") ? resource : withPublicBase(resource)}")`;
}

export function getCurrentAppearance() { return currentAppearance; }

export function applyResolvedAppearance(appearance: ResolvedAppearance) {
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    root.dataset.theme = appearance.themeId;
    root.dataset.colorScheme = appearance.scheme;
    root.dataset.styleProfile = appearance.styleProfile;
    root.dataset.motionProfile = appearance.motionProfile;
    root.dataset.materialShape = appearance.material.shape;
    root.dataset.materialGlass = appearance.material.glass;
    root.dataset.materialGlow = appearance.material.glow;
    root.dataset.materialDepth = appearance.material.depth;
    root.dataset.illustrationScenes = "workbench,adminCenter,agentManager";
    root.style.colorScheme = appearance.scheme;
    for (const name of Object.keys(currentAppearance.cssVariables)) {
      if (!(name in appearance.cssVariables)) root.style.removeProperty(name);
    }
    for (const [name, value] of Object.entries(appearance.cssVariables)) root.style.setProperty(name, value);
    const illustrationVariables: Record<string, string> = {
      "--theme-illustration-opacity": String(appearance.illustrations.opacity),
    };
    for (const surface of THEME_ILLUSTRATION_SURFACES) {
      illustrationVariables[`--theme-illustration-${surface}-image`] = illustrationCssImage(appearance.illustrations.resources[surface]);
      illustrationVariables[`--theme-illustration-${surface}-images`] = appearance.illustrations.sceneResources[surface]
        .map(illustrationCssImage)
        .join(", ");
      illustrationVariables[`--theme-illustration-${surface}-layer-count`] = String(appearance.illustrations.scenes[surface].layers.length);
      illustrationVariables[`--theme-illustration-${surface}-enabled`] = appearance.illustrations.surfaces[surface] ? "1" : "0";
    }
    for (const name of Object.keys(currentAppearance.illustrations ? {
      "--theme-illustration-opacity": "",
      ...Object.fromEntries(THEME_ILLUSTRATION_SURFACES.flatMap((surface) => [
        [`--theme-illustration-${surface}-image`, ""],
        [`--theme-illustration-${surface}-images`, ""],
        [`--theme-illustration-${surface}-layer-count`, ""],
        [`--theme-illustration-${surface}-enabled`, ""],
      ])),
    } : {})) {
      if (!(name in illustrationVariables)) root.style.removeProperty(name);
    }
    for (const [name, value] of Object.entries(illustrationVariables)) root.style.setProperty(name, value);
    document.querySelector<HTMLLinkElement>("link[data-theme-favicon]")?.setAttribute("href", withPublicBase("/assets/app-logo-classic.svg"));
  }
  if (currentAppearance.revision === appearance.revision) return;
  currentAppearance = appearance;
  for (const listener of listeners) listener();
}

export function useResolvedAppearance() {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    getCurrentAppearance,
    () => paperAppearance,
  );
}

export function resolvedTerminalTheme(appearance = currentAppearance, transparentBackground = false) {
  return Object.fromEntries(THEME_TOKENS.filter((token) => token.terminal)
    .map((token) => [
      token.terminal!,
      transparentBackground && token.terminal === "background" ? "rgba(0, 0, 0, 0)" : appearance.colors[token.key],
    ]));
}
