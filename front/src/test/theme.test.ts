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
  type UiThemeName,
} from "../theme";
import { withPublicBase } from "../utils/publicBase";

const NEW_THEME_NAMES = ["lunar-ceramic", "copper-night", "eclipse-film"] as const;

const NEW_TERMINAL_THEMES = [
  {
    name: "lunar-ceramic",
    background: "#e8e6e2",
    foreground: "#25282e",
    cursor: "#615a88",
    accent: "#615a88",
  },
  {
    name: "copper-night",
    background: "#191514",
    foreground: "#f3e6d4",
    cursor: "#d4874d",
    accent: "#d4874d",
  },
  {
    name: "eclipse-film",
    background: "#15171c",
    foreground: "#e7e4dc",
    cursor: "#aab6ca",
    accent: "#7689a8",
  },
] as const;

const APPROVED_THEME_PREVIEWS = [
  {
    value: "lunar-ceramic",
    preview: {
      accent: "#615a88",
      surface: "#f4f2ee",
      accentStrong: "#934737",
      border: "rgba(45, 48, 54, 0.14)",
      text: "#2d3036",
      muted: "#696d77",
    },
  },
  {
    value: "copper-night",
    preview: {
      accent: "#d88955",
      surface: "#1e1316",
      accentStrong: "#a692d7",
      border: "rgba(239, 199, 165, 0.16)",
      text: "#f3e5d4",
      muted: "#b6a092",
    },
  },
  {
    value: "eclipse-film",
    preview: {
      accent: "#c47791",
      surface: "#1a1b24",
      accentStrong: "#9bcbdd",
      border: "#707486",
      text: "#f1eff4",
      muted: "#a7a6b5",
    },
  },
] as const;

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

describe("future UI themes", () => {
  beforeEach(() => {
    localStorage.clear();
    document.querySelectorAll("link[data-theme-favicon]").forEach((node) => node.remove());
  });

  it("keeps UI_THEME_NAMES and UI_THEME_OPTIONS one-to-one with Chinese labels for the new themes", () => {
    const themeNames = UI_THEME_NAMES as readonly string[];
    const optionValues = UI_THEME_OPTIONS.map((option) => option.value);

    expect(new Set(themeNames).size).toBe(themeNames.length);
    expect([...optionValues].sort()).toEqual([...themeNames].sort());

    for (const name of NEW_THEME_NAMES) {
      expect(themeNames).toContain(name);
      expect(UI_THEME_OPTIONS).toContainEqual(expect.objectContaining({
        value: name,
        label: expect.stringMatching(/\p{Script=Han}/u),
      }));
    }
  });

  it("classifies lunar-ceramic as light and the two night themes as dark", () => {
    expect(isLightUiTheme("lunar-ceramic")).toBe(true);
    expect(isLightUiTheme("copper-night")).toBe(false);
    expect(isLightUiTheme("eclipse-film")).toBe(false);
  });

  it("exposes the approved preview palettes for all three themes", () => {
    for (const expected of APPROVED_THEME_PREVIEWS) {
      expect(UI_THEME_OPTIONS).toContainEqual(expect.objectContaining(expected));
    }
  });

  it.each(NEW_TERMINAL_THEMES)("returns $name terminal colors and a 4.5 contrast minimum", ({
    name,
    background,
    foreground,
    cursor,
    accent,
  }) => {
    const terminalTheme = getTerminalTheme(name as UiThemeName);

    expect.soft(terminalTheme.background).toBe(background);
    expect.soft(terminalTheme.foreground).toBe(foreground);
    expect.soft(terminalTheme.cursor).toBe(cursor);
    expect.soft(terminalTheme.cyan).toBe(accent);
    expect.soft(getTerminalMinimumContrastRatio(name as UiThemeName)).toBe(4.5);
  });

  it("gives the lunar terminal a visible light-theme cursor and selection", () => {
    expect(getTerminalTheme("lunar-ceramic")).toMatchObject({
      cursorAccent: "#fcfbf8",
      selectionBackground: "#b4abc9",
      selectionForeground: "#25282e",
      selectionInactiveBackground: "#d2cdd9",
    });
  });

  it.each(NEW_THEME_NAMES)("accepts %s from localStorage", (name) => {
    localStorage.setItem(UI_THEME_STORAGE_KEY, name);

    expect(readStoredUiTheme()).toBe(name as UiThemeName);
  });

  it.each([
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
});
