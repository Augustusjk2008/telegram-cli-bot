export type UiThemeName = "deep-space" | "classic";
export type ChatBodyFontFamilyName = "sans" | "serif" | "kai" | "fangsong" | "mono";
export type ChatBodyFontSizeName = "small" | "medium" | "large";
export type ChatBodyLineHeightName = "tight" | "normal" | "relaxed";
export type ChatBodyParagraphSpacingName = "tight" | "normal" | "relaxed";

export const APP_NAME = "🦞Safe Claw";
export const APP_YEAR = "2026";
export const UI_THEME_STORAGE_KEY = "web-ui-theme";
export const CHAT_BODY_FONT_FAMILY_STORAGE_KEY = "web-chat-body-font-family";
export const CHAT_BODY_FONT_SIZE_STORAGE_KEY = "web-chat-body-font-size";
export const CHAT_BODY_LINE_HEIGHT_STORAGE_KEY = "web-chat-body-line-height";
export const CHAT_BODY_PARAGRAPH_SPACING_STORAGE_KEY = "web-chat-body-paragraph-spacing";
export const DEFAULT_UI_THEME: UiThemeName = "deep-space";
export const DEFAULT_CHAT_BODY_FONT_FAMILY: ChatBodyFontFamilyName = "sans";
export const DEFAULT_CHAT_BODY_FONT_SIZE: ChatBodyFontSizeName = "medium";
export const DEFAULT_CHAT_BODY_LINE_HEIGHT: ChatBodyLineHeightName = "normal";
export const DEFAULT_CHAT_BODY_PARAGRAPH_SPACING: ChatBodyParagraphSpacingName = "normal";

export const UI_THEME_OPTIONS: Array<{
  value: UiThemeName;
  label: string;
  description: string;
  preview: {
    accent: string;
    surface: string;
    accentStrong: string;
    border: string;
    text: string;
    muted: string;
  };
}> = [
  {
    value: "deep-space",
    label: "深空轨道",
    description: "冷色深空控制台风格，适合展示安全、自主可控与任务编排。",
    preview: {
      accent: "#61cbff",
      surface: "#0b1931",
      accentStrong: "#7af6d6",
      border: "rgba(142, 189, 255, 0.18)",
      text: "#eaf4ff",
      muted: "#90a9c7",
    },
  },
  {
    value: "classic",
    label: "经典暖色",
    description: "延续现有暖色工作界面，阅读压力更低，适合日常使用。",
    preview: {
      accent: "#0f8c78",
      surface: "#fffaf3",
      accentStrong: "#d98b2b",
      border: "rgba(46, 37, 28, 0.08)",
      text: "#1d1b18",
      muted: "#6d675f",
    },
  },
];

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

function isUiThemeName(value: string): value is UiThemeName {
  return value === "deep-space" || value === "classic";
}

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
  if (typeof window === "undefined") {
    return DEFAULT_UI_THEME;
  }
  try {
    const raw = window.localStorage.getItem(UI_THEME_STORAGE_KEY)?.trim() || "";
    return isUiThemeName(raw) ? raw : DEFAULT_UI_THEME;
  } catch {
    return DEFAULT_UI_THEME;
  }
}

export function persistUiTheme(themeName: UiThemeName) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(UI_THEME_STORAGE_KEY, themeName);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

export function applyUiTheme(themeName: UiThemeName) {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.dataset.theme = themeName;
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

export function getTerminalTheme(themeName: UiThemeName) {
  if (themeName === "classic") {
    return {
      background: "#132033",
      foreground: "#eef3f8",
      cursor: "#fffaf3",
      black: "#1b2431",
      red: "#e76f51",
      green: "#3d8f5f",
      yellow: "#d49d2e",
      blue: "#5b8def",
      magenta: "#b07ae5",
      cyan: "#2b8c86",
      white: "#ecf2f8",
      brightBlack: "#5b6572",
      brightRed: "#f08f78",
      brightGreen: "#62b07d",
      brightYellow: "#e4b857",
      brightBlue: "#8db1ff",
      brightMagenta: "#c7a0ef",
      brightCyan: "#57b7af",
      brightWhite: "#ffffff",
    };
  }

  return {
    background: "#07111d",
    foreground: "#dce7f3",
    cursor: "#f8fafc",
    black: "#0f172a",
    red: "#ef4444",
    green: "#22c55e",
    yellow: "#f59e0b",
    blue: "#60a5fa",
    magenta: "#c084fc",
    cyan: "#22d3ee",
    white: "#e2e8f0",
    brightBlack: "#334155",
    brightRed: "#f87171",
    brightGreen: "#4ade80",
    brightYellow: "#fbbf24",
    brightBlue: "#93c5fd",
    brightMagenta: "#d8b4fe",
    brightCyan: "#67e8f9",
    brightWhite: "#f8fafc",
  };
}
