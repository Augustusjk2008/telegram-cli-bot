import { useSyncExternalStore } from "react";
import { withPublicBase } from "../utils/publicBase";
import { BUILTIN_THEME, resolveAppearance, THEME_TOKENS } from "./resolveAppearance";
import type { ResolvedAppearance } from "./types";

const paperAppearance = resolveAppearance(BUILTIN_THEME);
let currentAppearance = paperAppearance;
const listeners = new Set<() => void>();

export function getCurrentAppearance() { return currentAppearance; }

export function applyResolvedAppearance(appearance: ResolvedAppearance) {
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    root.dataset.theme = appearance.themeId;
    root.dataset.colorScheme = appearance.scheme;
    root.dataset.styleProfile = appearance.styleProfile;
    root.dataset.motionProfile = appearance.motionProfile;
    root.style.colorScheme = appearance.scheme;
    for (const name of Object.keys(currentAppearance.cssVariables)) {
      if (!(name in appearance.cssVariables)) root.style.removeProperty(name);
    }
    for (const [name, value] of Object.entries(appearance.cssVariables)) root.style.setProperty(name, value);
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

export function resolvedTerminalTheme(appearance = currentAppearance) {
  return Object.fromEntries(THEME_TOKENS.filter((token) => token.terminal)
    .map((token) => [token.terminal!, appearance.colors[token.key]]));
}
