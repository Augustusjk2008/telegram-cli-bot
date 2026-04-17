import { afterEach, expect, test } from "vitest";
import {
  DESKTOP_MIN_WIDTH,
  readStoredViewMode,
  resolveEffectiveLayoutMode,
  storeViewMode,
} from "../app/layoutMode";

afterEach(() => {
  localStorage.clear();
});

test("auto resolves to desktop at and above 1280px", () => {
  expect(resolveEffectiveLayoutMode("auto", DESKTOP_MIN_WIDTH - 1)).toBe("mobile");
  expect(resolveEffectiveLayoutMode("auto", DESKTOP_MIN_WIDTH)).toBe("desktop");
  expect(resolveEffectiveLayoutMode("desktop", 480)).toBe("desktop");
  expect(resolveEffectiveLayoutMode("mobile", 1920)).toBe("mobile");
});

test("stored mode falls back to auto when storage is invalid", () => {
  localStorage.setItem("web-view-mode", "broken");
  expect(readStoredViewMode()).toBe("auto");
  storeViewMode("desktop");
  expect(localStorage.getItem("web-view-mode")).toBe("desktop");
});
