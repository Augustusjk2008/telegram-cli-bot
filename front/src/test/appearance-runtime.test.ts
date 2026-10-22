import { afterEach, describe, expect, it } from "vitest";
import { applyResolvedAppearance, getCurrentAppearance } from "../theme/appearanceRuntime";
import { BUILTIN_THEME, contrastRatio, normalizeColor, resolveAppearance } from "../theme/resolveAppearance";
import type { PersonalTheme } from "../theme/types";

const custom = (overrides: Record<string, string> = {}): PersonalTheme => ({
  ...BUILTIN_THEME, id: "theme_personal", readonly: false,
  appearance: { colors: { scheme: "dark", overrides } },
});

afterEach(() => applyResolvedAppearance(resolveAppearance(BUILTIN_THEME)));

describe("personal theme colors", () => {
  it("normalizes hex while enforcing opaque canvas values", () => {
    expect(normalizeColor("#aBc")).toBe("#AABBCCFF");
    expect(normalizeColor("#abcd")).toBe("#AABBCCDD");
    expect(normalizeColor("#abcdef80", false)).toBeNull();
    expect(normalizeColor("url(https://example.com)")).toBeNull();
    expect(() => resolveAppearance(custom({ canvas: "#ffffff00" }))).toThrow();
    expect(() => resolveAppearance(custom({ "unknown.color": "#ffffff" }))).toThrow();
    expect(() => resolveAppearance({ ...custom(), schemaVersion: 2 } as unknown as PersonalTheme)).toThrow("版本");
  });

  it("derived colors follow a source until independently overridden", () => {
    const following = resolveAppearance(custom({ accent: "#123456" }));
    const overridden = resolveAppearance(custom({ accent: "#123456", "accent.soft": "#ABCDEF80" }));
    expect(following.colors["accent.soft"].slice(0, 7)).toBe("#123456");
    expect(overridden.colors["accent.soft"]).toBe("#ABCDEF80");
    expect(resolveAppearance(custom({ accent: "#123456" })).colors).toEqual(following.colors);
  });

  it("updates colors with a stable identity and fixed paper style", () => {
    const first = resolveAppearance(custom({ accent: "#123456" }));
    const next = resolveAppearance(custom({ accent: "#654321" }));
    applyResolvedAppearance(first);
    applyResolvedAppearance(next);
    expect(next.revision).not.toBe(first.revision);
    expect(getCurrentAppearance()).toBe(next);
    expect(document.documentElement.dataset).toMatchObject({ theme: "theme_personal", colorScheme: "dark", styleProfile: "paper", motionProfile: "paper" });
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#654321FF");
  });

  it("composites translucent foregrounds for contrast hints", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBe(21);
    expect(contrastRatio("#00000000", "#FFFFFF")).toBe(1);
  });
});
