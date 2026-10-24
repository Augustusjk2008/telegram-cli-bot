import { applyResolvedAppearance, getCurrentAppearance, resolvedTerminalTheme } from "./theme/appearanceRuntime";
import { BUILTIN_THEME, resolveAppearance } from "./theme/resolveAppearance";
export {
  CHAT_BODY_FONT_FAMILY_OPTIONS,
  CHAT_BODY_FONT_SIZE_OPTIONS,
  CHAT_BODY_LINE_HEIGHT_OPTIONS,
  CHAT_BODY_PARAGRAPH_SPACING_OPTIONS,
  DEFAULT_CHAT_BODY_FONT_FAMILY,
  DEFAULT_CHAT_BODY_FONT_SIZE,
  DEFAULT_CHAT_BODY_LINE_HEIGHT,
  DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  DEFAULT_CHAT_TYPOGRAPHY,
  chatTypographyCssVariables,
  getChatBodyFontFamilyValue,
  getChatBodyFontSizeValue,
  getChatBodyLineHeightValue,
  getChatBodyParagraphSpacingValue,
  isChatTypography,
  normalizeChatTypography,
} from "./theme/chatTypography";
export type {
  ChatBodyFontFamilyName,
  ChatBodyFontSizeName,
  ChatBodyLineHeightName,
  ChatBodyParagraphSpacingName,
  ChatTypography,
} from "./theme/types";

export const UI_THEME_NAMES = ["paper-daylight"] as const;
export type UiThemeName = string;

export const APP_NAME = "Orbit Safe Claw";
export const APP_LOGIN_NAME = "Orbit Safe Claw";
export const APP_VERSION = __APP_VERSION__;
export const APP_KICKER = "LOCAL AGENT CONTROL SURFACE";
export const UI_THEME_STORAGE_KEY = "web-ui-theme";
export const CHAT_ENTER_TO_SEND_STORAGE_KEY = "web-chat-enter-to-send";
export const DEFAULT_UI_THEME: UiThemeName = "paper-daylight";

const paper = resolveAppearance(BUILTIN_THEME);
export const UI_THEME_OPTIONS = [{
  value: BUILTIN_THEME.id,
  label: BUILTIN_THEME.name,
  description: "明亮纸白界面搭配陶橙与柔和蓝灰，适合日间阅读。",
  preview: {
    accent: paper.colors.accent,
    surface: paper.colors["surface.base"],
    accentStrong: paper.colors["accent.strong"],
    border: paper.colors.border,
    text: paper.colors["text.primary"],
    muted: paper.colors["text.muted"],
  },
}];

export function isLightUiTheme(themeName: string | undefined) {
  const current = getCurrentAppearance();
  return current.themeId === themeName ? current.scheme === "light" : true;
}

export function readStoredUiTheme(): UiThemeName {
  // The shared library is restored after authentication.
  persistUiTheme(DEFAULT_UI_THEME);
  return DEFAULT_UI_THEME;
}

export function persistUiTheme(_themeName: UiThemeName) {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(UI_THEME_STORAGE_KEY, DEFAULT_UI_THEME); } catch { /* Storage is optional. */ }
}

export function applyUiTheme(themeName: UiThemeName) {
  const current = getCurrentAppearance();
  applyResolvedAppearance(current.themeId === themeName ? current : paper);
}

function getDefaultChatEnterToSend() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }
  try {
    return window.matchMedia("(pointer: fine)").matches;
  } catch {
    return true;
  }
}

export function readStoredChatEnterToSend() {
  const fallback = getDefaultChatEnterToSend();
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(CHAT_ENTER_TO_SEND_STORAGE_KEY)?.trim();
    if (raw === "true") {
      return true;
    }
    if (raw === "false") {
      return false;
    }
  } catch {
    return fallback;
  }
  return fallback;
}

export function persistChatEnterToSend(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(CHAT_ENTER_TO_SEND_STORAGE_KEY, String(enabled));
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

export function getTerminalTheme(themeName: UiThemeName = getCurrentAppearance().themeId) {
  const current = getCurrentAppearance();
  return resolvedTerminalTheme(current.themeId === themeName ? current : paper);
}

export function getTerminalMinimumContrastRatio(_themeName?: UiThemeName) {
  return 4.5;
}
