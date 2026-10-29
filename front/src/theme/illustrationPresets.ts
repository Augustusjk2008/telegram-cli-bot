import type {
  ThemeIllustrationSetId,
  ThemeIllustrationSurface,
  ThemeIllustrations,
} from "./types";

export const THEME_ILLUSTRATION_SURFACES = [
  "workbench",
  "chat",
  "topbar",
  "management",
] as const satisfies readonly ThemeIllustrationSurface[];

export const THEME_ILLUSTRATION_SET_IDS = [
  "none",
  "forest-grove",
  "tidal-grove",
  "desert-dusk",
  "alpine-fog",
  "moonlit-garden",
] as const satisfies readonly ThemeIllustrationSetId[];

export const DEFAULT_THEME_ILLUSTRATIONS: ThemeIllustrations = {
  setId: "none",
  opacity: 0,
  surfaces: {
    workbench: false,
    chat: false,
    topbar: false,
    management: false,
  },
};

export const THEME_ILLUSTRATION_OPTIONS = [
  { id: "none", label: "无插画" },
  { id: "forest-grove", label: "森林绿" },
  { id: "tidal-grove", label: "潮汐蓝" },
  { id: "desert-dusk", label: "沙漠黄昏" },
  { id: "alpine-fog", label: "高山薄雾" },
  { id: "moonlit-garden", label: "月夜花园" },
  { id: "upload", label: "自定义上传" },
] as const;

export const ILLUSTRATION_TEMPLATES = [
  {
    id: "forest-grove",
    label: "森林绿",
    description: "苔绿、松针绿和陶橙",
    colors: { accent: "#A94A2EFF", "accent.strong": "#37685BFF" },
  },
  {
    id: "tidal-grove",
    label: "潮汐蓝",
    description: "深青、海蓝和珊瑚橙",
    colors: { accent: "#0B7285FF", "accent.strong": "#176B87FF" },
  },
  {
    id: "desert-dusk",
    label: "沙漠黄昏",
    description: "沙色、赭石和陶土色",
    colors: { accent: "#B45309FF", "accent.strong": "#8C5A2BFF" },
  },
  {
    id: "alpine-fog",
    label: "高山薄雾",
    description: "冰川蓝、雾灰和松绿",
    colors: { accent: "#2B7FFF", "accent.strong": "#3C6E71FF" },
  },
  {
    id: "moonlit-garden",
    label: "月夜花园",
    description: "靛蓝、炭黑和薰衣草色",
    colors: { accent: "#7C5CFCFF", "accent.strong": "#4C4B8FFF" },
  },
] as const;

export function illustrationResourcePath(
  setId: Exclude<ThemeIllustrationSetId, "upload">,
  surface: ThemeIllustrationSurface,
) {
  return `/assets/theme-illustrations/${setId}-${surface}.svg`;
}

export function defaultIllustrations(): ThemeIllustrations {
  return {
    setId: DEFAULT_THEME_ILLUSTRATIONS.setId,
    opacity: DEFAULT_THEME_ILLUSTRATIONS.opacity,
    surfaces: { ...DEFAULT_THEME_ILLUSTRATIONS.surfaces },
  };
}
