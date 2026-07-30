import { beforeEach, describe, expect, it } from "vitest";
import {
  DESKTOP_MIN_WIDTH,
  readStoredViewMode,
  resolveEffectiveLayoutMode,
  storeViewMode,
  VIEW_MODE_STORAGE_KEY,
} from "../app/layoutMode";

describe("layout mode boundary", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("switches auto mode exactly at the desktop breakpoint", () => {
    expect(resolveEffectiveLayoutMode("auto", DESKTOP_MIN_WIDTH - 1)).toBe("mobile");
    expect(resolveEffectiveLayoutMode("auto", DESKTOP_MIN_WIDTH)).toBe("desktop");
    expect(resolveEffectiveLayoutMode("auto", DESKTOP_MIN_WIDTH + 1)).toBe("desktop");
  });

  it("keeps explicit layout choices independent of viewport width", () => {
    expect(resolveEffectiveLayoutMode("desktop", 320)).toBe("desktop");
    expect(resolveEffectiveLayoutMode("mobile", 1920)).toBe("mobile");
  });

  it("persists only supported layout choices", () => {
    storeViewMode("desktop");
    expect(readStoredViewMode()).toBe("desktop");

    localStorage.setItem(VIEW_MODE_STORAGE_KEY, "compact");
    expect(readStoredViewMode()).toBe("auto");
  });
});
