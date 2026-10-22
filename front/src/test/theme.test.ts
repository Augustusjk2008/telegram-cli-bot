import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyUiTheme,
  CHAT_ENTER_TO_SEND_STORAGE_KEY,
  getTerminalMinimumContrastRatio,
  getTerminalTheme,
  isLightUiTheme,
  persistChatEnterToSend,
  persistUiTheme,
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
    document.querySelectorAll("link[data-theme-favicon]").forEach((node) => node.remove());
  });

  it("classifies light and dark themes", () => {
    expect(isLightUiTheme("paper-daylight")).toBe(true);
    expect(isLightUiTheme("obsidian-linear")).toBe(false);
    expect(isLightUiTheme("lunar-ceramic")).toBe(true);
    expect(isLightUiTheme("copper-night")).toBe(false);
    expect(isLightUiTheme("eclipse-film")).toBe(false);
  });

  it("defaults to deep-space for missing or unrecognized preferences", () => {
    expect(readStoredUiTheme()).toBe("deep-space");
    localStorage.setItem(UI_THEME_STORAGE_KEY, "unknown-theme");
    expect(readStoredUiTheme()).toBe("deep-space");
  });

  it.each(UI_THEME_NAMES)("persists and restores selectable theme %s", (name) => {
    expect(UI_THEME_OPTIONS.some((option) => option.value === name)).toBe(true);

    persistUiTheme(name);

    expect(localStorage.getItem(UI_THEME_STORAGE_KEY)).toBe(name);
    expect(readStoredUiTheme()).toBe(name);
  });

  it.each([
    ["obsidian-linear", "/assets/app-logo-favicon.svg"],
    ["paper-daylight", "/assets/app-logo-classic.svg"],
    ["lunar-ceramic", "/assets/app-logo-classic.svg"],
    ["copper-night", "/assets/app-logo-copper.svg"],
    ["eclipse-film", "/assets/app-logo-eclipse.svg"],
  ] as const)("updates the favicon when applying %s", (name, expectedHref) => {
    const favicon = document.createElement("link");
    favicon.setAttribute("rel", "icon");
    favicon.dataset.themeFavicon = "";
    favicon.setAttribute("href", "/assets/app-logo-favicon.svg");
    document.head.append(favicon);

    applyUiTheme(name);

    expect(document.documentElement.dataset.theme).toBe(name);
    expect(favicon.getAttribute("href")).toBe(withPublicBase(expectedHref));
  });

  it.each(["obsidian-linear", "paper-daylight"] as const)("provides readable terminal colors for %s", (name) => {
    const theme = getTerminalTheme(name);
    const ansiColors = [
      "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
      "brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue", "brightMagenta", "brightCyan", "brightWhite",
    ] as const;

    expect(getTerminalMinimumContrastRatio(name)).toBe(4.5);
    expect(theme).not.toEqual(getTerminalTheme("deep-space"));
    expect(relativeLuminance(theme.background) > relativeLuminance(theme.foreground)).toBe(isLightUiTheme(name));
    expect(contrastRatio(theme.foreground, theme.background)).toBeGreaterThanOrEqual(4.5);
    for (const color of ansiColors) {
      expect(theme[color]).toMatch(/^#[0-9a-f]{6}$/i);
      // ANSI black retains its background role in dark terminals; xterm adjusts text contrast.
      if (color !== "black" || isLightUiTheme(name)) {
        expect(contrastRatio(theme[color], theme.background), color).toBeGreaterThanOrEqual(4.5);
      }
    }
    expect(contrastRatio(theme.cursor, theme.background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(theme.cursorAccent!, theme.cursor)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(theme.selectionForeground!, theme.selectionBackground!)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(theme.selectionForeground!, theme.selectionInactiveBackground!)).toBeGreaterThanOrEqual(4.5);
  });
});
