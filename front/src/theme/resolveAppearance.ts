import catalog from "../../../bot/web/theme_catalog.json";
import type {
  ColorToken,
  ThemeIllustrations,
  ThemeIllustrationSurface,
  UiTheme,
  ResolvedAppearance,
  ThemeLibrary,
} from "./types";
import {
  chatTypographyCssVariables,
  DEFAULT_CHAT_TYPOGRAPHY,
  isChatTypography,
  normalizeChatTypography,
} from "./chatTypography";
import { PAPER_MOTION, PAPER_STYLE } from "./types";
import {
  defaultIllustrations,
  illustrationResourcePath,
  THEME_ILLUSTRATION_SET_IDS,
  THEME_ILLUSTRATION_SURFACES,
} from "./illustrationPresets";

export const THEME_TOKENS = catalog.tokens as ColorToken[];
export const BUILTIN_THEME: UiTheme = {
  schemaVersion: 1,
  id: "paper-daylight",
  name: "纸感日间",
  baseId: "paper-daylight",
  appearance: {
    colors: { scheme: "light", overrides: {} },
    typography: DEFAULT_CHAT_TYPOGRAPHY,
    illustrations: defaultIllustrations(),
  },
  readonly: true,
  updatedAt: "",
  version: 1,
};

export function builtinLibrary(): ThemeLibrary {
  return { schemaVersion: 1, scope: "global", revision: 0, selectedThemeId: BUILTIN_THEME.id, themes: [BUILTIN_THEME] };
}

export function normalizeColor(value: string, allowAlpha = true): string | null {
  let hex = value.trim().toUpperCase();
  if (!/^#(?:[0-9A-F]{3}|[0-9A-F]{4}|[0-9A-F]{6}|[0-9A-F]{8})$/.test(hex)) return null;
  if (hex.length === 4 || hex.length === 5) hex = `#${[...hex.slice(1)].map((c) => c + c).join("")}`;
  if (hex.length === 7) hex += "FF";
  return allowAlpha || hex.endsWith("FF") ? hex : null;
}

export function normalizeIllustrations(value: unknown): ThemeIllustrations {
  if (value === undefined) return defaultIllustrations();
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("主题插画配置无效");
  }
  const candidate = value as Record<string, unknown>;
  if (Object.keys(candidate).some((key) => !["setId", "opacity", "surfaces"].includes(key))) {
    throw new Error("主题插画配置包含不支持的字段");
  }
  if (!THEME_ILLUSTRATION_SET_IDS.includes(candidate.setId as typeof THEME_ILLUSTRATION_SET_IDS[number])) {
    throw new Error("主题插画资源无效");
  }
  if (typeof candidate.opacity !== "number" || !Number.isFinite(candidate.opacity) || candidate.opacity < 0 || candidate.opacity > 0.25) {
    throw new Error("主题插画透明度必须在 0 到 0.25 之间");
  }
  const surfaces = candidate.surfaces;
  if (!surfaces || typeof surfaces !== "object" || Array.isArray(surfaces)) {
    throw new Error("主题插画区域配置无效");
  }
  const surfaceRecord = surfaces as Record<string, unknown>;
  if (Object.keys(surfaceRecord).some((key) => !THEME_ILLUSTRATION_SURFACES.includes(key as ThemeIllustrationSurface))) {
    throw new Error("主题插画区域配置包含不支持的字段");
  }
  for (const surface of THEME_ILLUSTRATION_SURFACES) {
    if (typeof surfaceRecord[surface] !== "boolean") throw new Error("主题插画区域配置无效");
  }
  return {
    setId: candidate.setId as ThemeIllustrations["setId"],
    opacity: candidate.opacity,
    surfaces: Object.fromEntries(
      THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, surfaceRecord[surface] as boolean]),
    ) as ThemeIllustrations["surfaces"],
  };
}

export function resolveAppearance(theme: UiTheme): ResolvedAppearance {
  if (theme.schemaVersion !== 1) throw new Error("此主题使用了尚不支持的数据版本");
  const colors: Record<string, string> = {};
  const cssVariables: Record<string, string> = {};
  const tokens = new Map(THEME_TOKENS.map((token) => [token.key, token]));
  if (!theme.appearance || Object.keys(theme.appearance).some((key) => key !== "colors" && key !== "typography" && key !== "illustrations")
    || !theme.appearance.colors || !["light", "dark"].includes(theme.appearance.colors.scheme)
    || Object.keys(theme.appearance.colors).some((key) => key !== "scheme" && key !== "overrides")
    || !theme.appearance.colors.overrides || typeof theme.appearance.colors.overrides !== "object"
    || Array.isArray(theme.appearance.colors.overrides)
    || (theme.appearance.typography !== undefined && !isChatTypography(theme.appearance.typography))) throw new Error("此主题包含尚不支持的外观配置");
  const illustrations = normalizeIllustrations(theme.appearance.illustrations);
  for (const [key, value] of Object.entries(theme.appearance.colors.overrides)) {
    const token = tokens.get(key);
    if (!token || typeof value !== "string" || !normalizeColor(value, token.allowAlpha)) throw new Error(`主题颜色无效：${key}`);
  }
  const resolving = new Set<string>();
  const resolve = (key: string): string => {
    if (colors[key]) return colors[key];
    const token = tokens.get(key);
    if (!token || resolving.has(key)) throw new Error(`颜色目录中的依赖无效：${key}`);
    resolving.add(key);
    let value = normalizeColor(theme.appearance.colors.overrides[key] || "", token.allowAlpha);
    if (!value && token.derive) {
      let source = resolve(token.derive.from);
      if (token.derive.mix) source = mixColors(source, resolve(token.derive.mix.with), token.derive.mix.ratio);
      value = token.derive.alpha === undefined ? source
        : `${source.slice(0, 7)}${Math.round(token.derive.alpha * 255).toString(16).padStart(2, "0").toUpperCase()}`;
    }
    colors[key] = value || normalizeColor(token.default, token.allowAlpha)!;
    resolving.delete(key);
    return colors[key];
  };
  for (const token of THEME_TOKENS) {
    const value = resolve(token.key);
    if (token.cssVariable) cssVariables[token.cssVariable] = value;
  }
  const typography = normalizeChatTypography(theme.appearance.typography);
  Object.assign(cssVariables, chatTypographyCssVariables(typography));
  const resources = Object.fromEntries(
    THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, illustrationResourcePath(illustrations.setId, surface)]),
  ) as Record<ThemeIllustrationSurface, string>;
  const resolvedIllustrations = {
    ...illustrations,
    resources,
    colors: {
      primary: colors["accent.strong"] || colors.accent,
      secondary: colors.accent,
      soft: colors["accent.soft"] || colors.accent,
    },
  };
  // Identity alone cannot detect editing the selected theme in place.
  const revision = JSON.stringify([theme.id, theme.appearance.colors.scheme, colors, typography, resolvedIllustrations]);
  return { themeId: theme.id, scheme: theme.appearance.colors.scheme, typography, colors, cssVariables, styleProfile: "paper", motionProfile: "paper", style: PAPER_STYLE, motion: PAPER_MOTION, illustrations: resolvedIllustrations, revision };
}

function channels(color: string) {
  const hex = normalizeColor(color) || "#000000FF";
  return [1, 3, 5, 7].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255);
}

function mixColors(first: string, second: string, ratio: number) {
  const a = channels(first), b = channels(second);
  const alpha = a[3] * ratio + b[3] * (1 - ratio);
  const rgb = a.slice(0, 3).map((v, i) => alpha === 0 ? 0 : (v * a[3] * ratio + b[i] * b[3] * (1 - ratio)) / alpha);
  return `#${[...rgb, alpha].map((v) => Math.round(v * 255).toString(16).padStart(2, "0").toUpperCase()).join("")}`;
}

export function contrastRatio(foreground: string, background: string, canvas = "#FFFFFFFF"): number {
  const fg = channels(foreground);
  const bg = channels(background);
  const backdrop = channels(canvas);
  const opaqueBg = bg.slice(0, 3).map((v, index) => v * bg[3] + (backdrop[index] * backdrop[3] + 1 - backdrop[3]) * (1 - bg[3]));
  const compositeFg = fg.slice(0, 3).map((v, i) => v * fg[3] + opaqueBg[i] * (1 - fg[3]));
  const luminance = (rgb: number[]) => rgb.map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
    .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
  const a = luminance(compositeFg), b = luminance(opaqueBg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
