import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyUiTheme,
  CHAT_ENTER_TO_SEND_STORAGE_KEY,
  isLightUiTheme,
  persistChatEnterToSend,
  readStoredChatEnterToSend,
  readStoredUiTheme,
  UI_THEME_STORAGE_KEY,
  type UiThemeName,
} from "../theme";
import { withPublicBase } from "../utils/publicBase";

const NEW_THEME_NAMES = ["lunar-ceramic", "copper-night", "eclipse-film"] as const;


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

  it("classifies lunar-ceramic as light and the two night themes as dark", () => {
    expect(isLightUiTheme("lunar-ceramic")).toBe(true);
    expect(isLightUiTheme("copper-night")).toBe(false);
    expect(isLightUiTheme("eclipse-film")).toBe(false);
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
