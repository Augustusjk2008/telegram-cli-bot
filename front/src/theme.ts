export const UI_THEME_NAMES = ["deep-space", "classic", "graphite", "lab-light", "ink-paper", "high-contrast"] as const;
export type UiThemeName = typeof UI_THEME_NAMES[number];
export type ChatBodyFontFamilyName = "sans" | "serif" | "kai" | "fangsong" | "mono";
export type ChatBodyFontSizeName = "small" | "medium" | "large";
export type ChatBodyLineHeightName = "tight" | "normal" | "relaxed";
export type ChatBodyParagraphSpacingName = "tight" | "normal" | "relaxed";

export const APP_NAME = "Orbit Safe Claw";
export const APP_LOGIN_NAME = "Orbit Safe Claw";
export const APP_VERSION = __APP_VERSION__;
export const APP_TAGLINE = "你的随身智能体指挥中心";
export const APP_KICKER = "LOCAL AGENT CONTROL SURFACE";
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
      accent: "#6bd3ff",
      surface: "#0e192a",
      accentStrong: "#71f2d0",
      border: "rgba(151, 190, 239, 0.18)",
      text: "#eaf4ff",
      muted: "#9cb2ce",
    },
  },
  {
    value: "classic",
    label: "经典暖色",
    description: "延续现有暖色工作界面，阅读压力更低，适合日常使用。",
    preview: {
      accent: "#0e8f7f",
      surface: "#fffbf4",
      accentStrong: "#cc7a21",
      border: "rgba(52, 43, 31, 0.12)",
      text: "#1f1d1a",
      muted: "#6f685f",
    },
  },
  {
    value: "graphite",
    label: "石墨终端",
    description: "深灰工作台搭配绿与琥珀状态色，适合终端、Git 与调试场景。",
    preview: {
      accent: "#94df8e",
      surface: "#1d2225",
      accentStrong: "#e3b55b",
      border: "rgba(214, 222, 229, 0.17)",
      text: "#e8eaec",
      muted: "#a0a9b1",
    },
  },
  {
    value: "lab-light",
    label: "冷白实验室",
    description: "冷白与浅灰界面，蓝绿强调，适合办公、文件浏览和长时间阅读。",
    preview: {
      accent: "#2563eb",
      surface: "#ffffff",
      accentStrong: "#0f766e",
      border: "rgba(15, 23, 42, 0.12)",
      text: "#142033",
      muted: "#64748b",
    },
  },
  {
    value: "ink-paper",
    label: "墨纸",
    description: "低饱和纸面与墨色文字，减轻聊天与文档阅读疲劳。",
    preview: {
      accent: "#6f5f3d",
      surface: "#fffaf1",
      accentStrong: "#4f7771",
      border: "rgba(52, 43, 31, 0.13)",
      text: "#211d19",
      muted: "#766b5d",
    },
  },
  {
    value: "high-contrast",
    label: "高对比",
    description: "黑白强边界和高亮强调，适合投屏、弱光和可访问性场景。",
    preview: {
      accent: "#ffff00",
      surface: "#000000",
      accentStrong: "#00ffff",
      border: "#ffffff",
      text: "#ffffff",
      muted: "#d4d4d4",
    },
  },
];

export function isLightUiTheme(themeName: string | undefined): themeName is UiThemeName {
  return themeName === "classic" || themeName === "lab-light" || themeName === "ink-paper";
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

function isUiThemeName(value: string): value is UiThemeName {
  return (UI_THEME_NAMES as readonly string[]).includes(value);
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
      background: "#fbf7ef",
      foreground: "#1d1b18",
      cursor: "#0f8c78",
      black: "#2b241c",
      red: "#ba5938",
      green: "#2f7a52",
      yellow: "#9a6b19",
      blue: "#2d64b3",
      magenta: "#8e63c7",
      cyan: "#0f8c78",
      white: "#efe6d9",
      brightBlack: "#6d675f",
      brightRed: "#d47a58",
      brightGreen: "#52966d",
      brightYellow: "#b98a33",
      brightBlue: "#5382cc",
      brightMagenta: "#a986d8",
      brightCyan: "#3fa896",
      brightWhite: "#fffdf9",
    };
  }

  if (themeName === "graphite") {
    return {
      background: "#111315",
      foreground: "#e6e8ea",
      cursor: "#c6f57b",
      black: "#0b0d0f",
      red: "#ff6b64",
      green: "#8fdc8b",
      yellow: "#e3b55b",
      blue: "#75a7ff",
      magenta: "#c792ea",
      cyan: "#59d6c8",
      white: "#dfe3e6",
      brightBlack: "#586069",
      brightRed: "#ff8f87",
      brightGreen: "#b1f3ac",
      brightYellow: "#f0ca78",
      brightBlue: "#9cc0ff",
      brightMagenta: "#d9b2f4",
      brightCyan: "#8be8de",
      brightWhite: "#ffffff",
    };
  }

  if (themeName === "lab-light") {
    return {
      background: "#f8fafc",
      foreground: "#142033",
      cursor: "#0f766e",
      black: "#1f2937",
      red: "#b42318",
      green: "#157f3b",
      yellow: "#9a6700",
      blue: "#2563eb",
      magenta: "#7c3aed",
      cyan: "#0891b2",
      white: "#e5e7eb",
      brightBlack: "#64748b",
      brightRed: "#d92d20",
      brightGreen: "#16a34a",
      brightYellow: "#ca8a04",
      brightBlue: "#3b82f6",
      brightMagenta: "#8b5cf6",
      brightCyan: "#06b6d4",
      brightWhite: "#ffffff",
    };
  }

  if (themeName === "ink-paper") {
    return {
      background: "#f6f1e8",
      foreground: "#211d19",
      cursor: "#6f5f3d",
      black: "#2a241f",
      red: "#a14d3a",
      green: "#58784d",
      yellow: "#8a6b2d",
      blue: "#536f8d",
      magenta: "#7a5c7d",
      cyan: "#4f7771",
      white: "#eadfce",
      brightBlack: "#766b5d",
      brightRed: "#bd614c",
      brightGreen: "#6f925f",
      brightYellow: "#a2823e",
      brightBlue: "#6a84a3",
      brightMagenta: "#917095",
      brightCyan: "#67908a",
      brightWhite: "#fffaf2",
    };
  }

  if (themeName === "high-contrast") {
    return {
      background: "#000000",
      foreground: "#ffffff",
      cursor: "#ffff00",
      black: "#000000",
      red: "#ff4d4d",
      green: "#00ff66",
      yellow: "#ffff00",
      blue: "#5aa9ff",
      magenta: "#ff66ff",
      cyan: "#00ffff",
      white: "#f5f5f5",
      brightBlack: "#8a8a8a",
      brightRed: "#ff8080",
      brightGreen: "#66ff99",
      brightYellow: "#ffff66",
      brightBlue: "#8fc7ff",
      brightMagenta: "#ff9cff",
      brightCyan: "#66ffff",
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

export function getTerminalMinimumContrastRatio(themeName: UiThemeName) {
  if (themeName === "high-contrast") {
    return 7;
  }
  return isLightUiTheme(themeName) ? 4.5 : 1;
}
