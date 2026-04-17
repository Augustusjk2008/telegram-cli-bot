export type ViewMode = "auto" | "mobile" | "desktop";
export type EffectiveLayoutMode = "mobile" | "desktop";

export const VIEW_MODE_STORAGE_KEY = "web-view-mode";
export const DESKTOP_MIN_WIDTH = 1280;

export function readStoredViewMode(): ViewMode {
  try {
    const raw = localStorage.getItem(VIEW_MODE_STORAGE_KEY);
    return raw === "auto" || raw === "mobile" || raw === "desktop" ? raw : "auto";
  } catch {
    return "auto";
  }
}

export function storeViewMode(viewMode: ViewMode) {
  try {
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode);
  } catch {
    // Ignore storage failures and keep the in-memory value.
  }
}

export function resolveEffectiveLayoutMode(viewMode: ViewMode, viewportWidth: number): EffectiveLayoutMode {
  if (viewMode === "mobile") {
    return "mobile";
  }
  if (viewMode === "desktop") {
    return "desktop";
  }
  return viewportWidth >= DESKTOP_MIN_WIDTH ? "desktop" : "mobile";
}

export function readViewportWidth() {
  if (typeof window === "undefined") {
    return 1024;
  }
  return window.innerWidth;
}
