export type ColorScheme = "light" | "dark";

export type ChatBodyFontFamilyName = "sans" | "serif" | "kai" | "fangsong" | "mono";
export type ChatBodyFontSizeName = "small" | "medium" | "large";
export type ChatBodyLineHeightName = "tight" | "normal" | "relaxed";
export type ChatBodyParagraphSpacingName = "tight" | "normal" | "relaxed";

export type ChatTypography = {
  chatBodyFontFamily: ChatBodyFontFamilyName;
  chatBodyFontSize: ChatBodyFontSizeName;
  chatBodyLineHeight: ChatBodyLineHeightName;
  chatBodyParagraphSpacing: ChatBodyParagraphSpacingName;
};

export const PAPER_STYLE = { fileTreeRowHeight: 26 } as const;
export const PAPER_MOTION = { profile: "paper" } as const;

export type ThemeAppearance = {
  colors: { scheme: ColorScheme; overrides: Record<string, string> };
  typography?: ChatTypography;
};

export type UiTheme = {
  schemaVersion: 1;
  id: string;
  name: string;
  baseId: "paper-daylight";
  appearance: ThemeAppearance;
  readonly: boolean;
  updatedAt: string;
  version: number;
};

export type ThemeLibrary = {
  schemaVersion: 1;
  scope: "global";
  revision: number;
  selectedThemeId: string;
  themes: UiTheme[];
  error?: string;
};

export type ThemeCreateInput = {
  schemaVersion: 1;
  expectedRevision: number;
  sourceId: string;
  name: string;
  appearance?: ThemeAppearance;
  activate?: boolean;
};

export type ThemeUpdateInput = {
  schemaVersion: 1;
  expectedRevision: number;
  name?: string;
  appearance?: ThemeAppearance;
  activate?: boolean;
};

export type ColorToken = {
  key: string;
  label: string;
  group: string;
  description: string;
  cssVariable?: string;
  default: string;
  derive?: { from: string; alpha?: number; mix?: { with: string; ratio: number } };
  allowAlpha: boolean;
  contrastAgainst?: string | string[];
  minContrast?: number;
  terminal?: string;
};

export type ResolvedAppearance = {
  themeId: string;
  scheme: ColorScheme;
  typography: ChatTypography;
  colors: Record<string, string>;
  cssVariables: Record<string, string>;
  styleProfile: "paper";
  motionProfile: "paper";
  style: typeof PAPER_STYLE;
  motion: typeof PAPER_MOTION;
  revision: string;
};
