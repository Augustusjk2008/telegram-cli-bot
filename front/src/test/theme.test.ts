import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyUiTheme,
  CHAT_ENTER_TO_SEND_STORAGE_KEY,
  getTerminalMinimumContrastRatio,
  getTerminalTheme,
  isLightUiTheme,
  persistChatEnterToSend,
  readStoredChatEnterToSend,
  readStoredUiTheme,
  UI_THEME_NAMES,
  UI_THEME_OPTIONS,
  UI_THEME_STORAGE_KEY,
} from "../theme";
import { withPublicBase } from "../utils/publicBase";

function relativeLuminance(color: string) {
  const [red, green, blue] = [1, 3, 5].map((offset) => {
    const channel = Number.parseInt(color.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}

function contrastRatio(foreground: string, background: string) {
  const luminances = [relativeLuminance(foreground), relativeLuminance(background)];
  return (Math.max(...luminances) + 0.05) / (Math.min(...luminances) + 0.05);
}

describe("chat Enter-to-send preference", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to newline on coarse-pointer devices", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));

    expect(readStoredChatEnterToSend()).toBe(false);
  });

  it("defaults to Enter-to-send on fine-pointer devices", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));

    expect(readStoredChatEnterToSend()).toBe(true);
  });

  it("persists an explicit preference that overrides the device default", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));

    persistChatEnterToSend(true);

    expect(localStorage.getItem(CHAT_ENTER_TO_SEND_STORAGE_KEY)).toBe("true");
    expect(readStoredChatEnterToSend()).toBe(true);
  });
});

describe("UI themes", () => {
  beforeEach(() => {
    localStorage.clear();
    applyUiTheme("paper-daylight");
    document.querySelectorAll("link[data-theme-favicon]").forEach((node) => node.remove());
  });

  it.each([null, "deep-space", "classic", "obsidian-linear", "theme_missing"])("migrates unauthenticated preference %s to paper", (name) => {
    if (name) localStorage.setItem(UI_THEME_STORAGE_KEY, name);
    expect(readStoredUiTheme()).toBe("paper-daylight");
    expect(localStorage.getItem(UI_THEME_STORAGE_KEY)).toBe("paper-daylight");
    expect(UI_THEME_NAMES).toEqual(["paper-daylight"]);
    expect(UI_THEME_OPTIONS.map((option) => option.value)).toEqual(["paper-daylight"]);
  });

  it("uses the paper favicon and fully falls back for an unknown identity", () => {
    const favicon = document.createElement("link");
    favicon.dataset.themeFavicon = "";
    document.head.append(favicon);
    applyUiTheme("theme_missing");
    expect(document.documentElement.dataset.theme).toBe("paper-daylight");
    expect(isLightUiTheme("theme_missing")).toBe(true);
    expect(favicon.getAttribute("href")).toBe(withPublicBase("/assets/app-logo-classic.svg"));
  });

  it("provides a readable terminal baseline", () => {
    const theme = getTerminalTheme("paper-daylight");
    expect(getTerminalMinimumContrastRatio()).toBe(4.5);
    expect(contrastRatio(theme.foreground, theme.background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(theme.cursor, theme.background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(theme.selectionForeground, theme.selectionBackground)).toBeGreaterThanOrEqual(4.5);
  });
});
