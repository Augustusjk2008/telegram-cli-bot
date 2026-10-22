import { applyResolvedAppearance, getCurrentAppearance, resolvedTerminalTheme } from "./theme/appearanceRuntime";
import { BUILTIN_THEME, resolveAppearance } from "./theme/resolveAppearance";

export const UI_THEME_NAMES = ["paper-daylight"] as const;
export type UiThemeName = string;
export type ChatBodyFontFamilyName = "sans" | "serif" | "kai" | "fangsong" | "mono";
export type ChatBodyFontSizeName = "small" | "medium" | "large";
export type ChatBodyLineHeightName = "tight" | "normal" | "relaxed";
export type ChatBodyParagraphSpacingName = "tight" | "normal" | "relaxed";

export const APP_NAME = "Orbit Safe Claw";
export const APP_LOGIN_NAME = "Orbit Safe Claw";
export const APP_VERSION = __APP_VERSION__;
export const APP_KICKER = "LOCAL AGENT CONTROL SURFACE";
export const UI_THEME_STORAGE_KEY = "web-ui-theme";
export const CHAT_BODY_FONT_FAMILY_STORAGE_KEY = "web-chat-body-font-family";
export const CHAT_BODY_FONT_SIZE_STORAGE_KEY = "web-chat-body-font-size";
export const CHAT_BODY_LINE_HEIGHT_STORAGE_KEY = "web-chat-body-line-height";
export const CHAT_BODY_PARAGRAPH_SPACING_STORAGE_KEY = "web-chat-body-paragraph-spacing";
export const CHAT_ENTER_TO_SEND_STORAGE_KEY = "web-chat-enter-to-send";
export const DEFAULT_UI_THEME: UiThemeName = "paper-daylight";
export const DEFAULT_CHAT_BODY_FONT_FAMILY: ChatBodyFontFamilyName = "sans";
export const DEFAULT_CHAT_BODY_FONT_SIZE: ChatBodyFontSizeName = "medium";
export const DEFAULT_CHAT_BODY_LINE_HEIGHT: ChatBodyLineHeightName = "normal";
export const DEFAULT_CHAT_BODY_PARAGRAPH_SPACING: ChatBodyParagraphSpacingName = "normal";

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

export const CHAT_BODY_FONT_FAMILY_OPTIONS: Array<{
  value: ChatBodyFontFamilyName;
  label: string;
}> = [
  { value: "sans", label: "系统默认" },
  { value: "serif", label: "宋体阅读" },
  { value: "kai", label: "楷体阅读" },
  { value: "fangsong", label: "仿宋阅读" },
  { value: "mono", label: "代码字体" },
];

export const CHAT_BODY_FONT_SIZE_OPTIONS: Array<{
  value: ChatBodyFontSizeName;
  label: string;
}> = [
  { value: "small", label: "小" },
  { value: "medium", label: "中" },
  { value: "large", label: "大" },
];

export const CHAT_BODY_LINE_HEIGHT_OPTIONS: Array<{
  value: ChatBodyLineHeightName;
  label: string;
}> = [
  { value: "tight", label: "紧凑" },
  { value: "normal", label: "标准" },
  { value: "relaxed", label: "宽松" },
];

export const CHAT_BODY_PARAGRAPH_SPACING_OPTIONS: Array<{
  value: ChatBodyParagraphSpacingName;
  label: string;
}> = [
  { value: "tight", label: "紧凑" },
  { value: "normal", label: "标准" },
  { value: "relaxed", label: "宽松" },
];

function isChatBodyFontFamilyName(value: string): value is ChatBodyFontFamilyName {
  return value === "sans" || value === "serif" || value === "kai" || value === "fangsong" || value === "mono";
}

function isChatBodyFontSizeName(value: string): value is ChatBodyFontSizeName {
  return value === "small" || value === "medium" || value === "large";
}

function isChatBodyLineHeightName(value: string): value is ChatBodyLineHeightName {
  return value === "tight" || value === "normal" || value === "relaxed";
}

function isChatBodyParagraphSpacingName(value: string): value is ChatBodyParagraphSpacingName {
  return value === "tight" || value === "normal" || value === "relaxed";
}

export function readStoredUiTheme(): UiThemeName {
  // Personal preferences are restored only after the server confirms identity.
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

export function readStoredChatBodyFontFamily(): ChatBodyFontFamilyName {
  if (typeof window === "undefined") {
    return DEFAULT_CHAT_BODY_FONT_FAMILY;
  }
  try {
    const raw = window.localStorage.getItem(CHAT_BODY_FONT_FAMILY_STORAGE_KEY)?.trim() || "";
    return isChatBodyFontFamilyName(raw) ? raw : DEFAULT_CHAT_BODY_FONT_FAMILY;
  } catch {
    return DEFAULT_CHAT_BODY_FONT_FAMILY;
  }
}

export function persistChatBodyFontFamily(fontFamily: ChatBodyFontFamilyName) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(CHAT_BODY_FONT_FAMILY_STORAGE_KEY, fontFamily);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

export function readStoredChatBodyFontSize(): ChatBodyFontSizeName {
  if (typeof window === "undefined") {
    return DEFAULT_CHAT_BODY_FONT_SIZE;
  }
  try {
    const raw = window.localStorage.getItem(CHAT_BODY_FONT_SIZE_STORAGE_KEY)?.trim() || "";
    return isChatBodyFontSizeName(raw) ? raw : DEFAULT_CHAT_BODY_FONT_SIZE;
  } catch {
    return DEFAULT_CHAT_BODY_FONT_SIZE;
  }
}

export function persistChatBodyFontSize(fontSize: ChatBodyFontSizeName) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(CHAT_BODY_FONT_SIZE_STORAGE_KEY, fontSize);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

export function readStoredChatBodyLineHeight(): ChatBodyLineHeightName {
  if (typeof window === "undefined") {
    return DEFAULT_CHAT_BODY_LINE_HEIGHT;
  }
  try {
    const raw = window.localStorage.getItem(CHAT_BODY_LINE_HEIGHT_STORAGE_KEY)?.trim() || "";
    return isChatBodyLineHeightName(raw) ? raw : DEFAULT_CHAT_BODY_LINE_HEIGHT;
  } catch {
    return DEFAULT_CHAT_BODY_LINE_HEIGHT;
  }
}

export function persistChatBodyLineHeight(lineHeight: ChatBodyLineHeightName) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(CHAT_BODY_LINE_HEIGHT_STORAGE_KEY, lineHeight);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

export function readStoredChatBodyParagraphSpacing(): ChatBodyParagraphSpacingName {
  if (typeof window === "undefined") {
    return DEFAULT_CHAT_BODY_PARAGRAPH_SPACING;
  }
  try {
    const raw = window.localStorage.getItem(CHAT_BODY_PARAGRAPH_SPACING_STORAGE_KEY)?.trim() || "";
    return isChatBodyParagraphSpacingName(raw) ? raw : DEFAULT_CHAT_BODY_PARAGRAPH_SPACING;
  } catch {
    return DEFAULT_CHAT_BODY_PARAGRAPH_SPACING;
  }
}

export function persistChatBodyParagraphSpacing(paragraphSpacing: ChatBodyParagraphSpacingName) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(CHAT_BODY_PARAGRAPH_SPACING_STORAGE_KEY, paragraphSpacing);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
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

export function getChatBodyFontFamilyValue(fontFamily: ChatBodyFontFamilyName) {
  if (fontFamily === "kai") {
    return '"KaiTi", "Kaiti SC", "STKaiti", serif';
  }
  if (fontFamily === "fangsong") {
    return '"FangSong", "STFangsong", serif';
  }
  if (fontFamily === "serif") {
    return '"SimSun", "Songti SC", "STSong", serif';
  }
  if (fontFamily === "mono") {
    return '"Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace';
  }
  return '"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
}

export function getChatBodyFontSizeValue(fontSize: ChatBodyFontSizeName) {
  if (fontSize === "small") {
    return "14px";
  }
  if (fontSize === "large") {
    return "17px";
  }
  return "15px";
}

export function getChatBodyLineHeightValue(lineHeight: ChatBodyLineHeightName) {
  if (lineHeight === "tight") {
    return "1.65";
  }
  if (lineHeight === "relaxed") {
    return "2.1";
  }
  return "1.9";
}

export function getChatBodyParagraphSpacingValue(paragraphSpacing: ChatBodyParagraphSpacingName) {
  if (paragraphSpacing === "tight") {
    return "0.45em";
  }
  if (paragraphSpacing === "relaxed") {
    return "1.1em";
  }
  return "0.75em";
}

export function applyChatReadingPreferences(
  fontFamily: ChatBodyFontFamilyName,
  fontSize: ChatBodyFontSizeName,
  lineHeight: ChatBodyLineHeightName,
  paragraphSpacing: ChatBodyParagraphSpacingName,
) {
  if (typeof document === "undefined") {
    return;
  }

  const root = document.documentElement;

  root.style.setProperty("--chat-body-font-family", getChatBodyFontFamilyValue(fontFamily));
  root.style.setProperty("--chat-body-font-size", getChatBodyFontSizeValue(fontSize));
  root.style.setProperty("--chat-body-line-height", getChatBodyLineHeightValue(lineHeight));
  root.style.setProperty("--chat-body-paragraph-spacing", getChatBodyParagraphSpacingValue(paragraphSpacing));
}

export function getTerminalTheme(themeName: UiThemeName = getCurrentAppearance().themeId) {
  const current = getCurrentAppearance();
  return resolvedTerminalTheme(current.themeId === themeName ? current : paper);
}

export function getTerminalMinimumContrastRatio(_themeName?: UiThemeName) {
  return 4.5;
}
