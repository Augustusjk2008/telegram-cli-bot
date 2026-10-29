import type {
  ThemeIllustrationAsset,
  ThemeIllustrationSetId,
  ThemeIllustrationSurface,
  ThemeIllustrations,
} from "./types";
import catalog from "../../../bot/web/theme_illustrations.json";

export const THEME_ILLUSTRATION_SURFACES = [
  "workbench",
  "adminCenter",
  "agentManager",
] as const satisfies readonly ThemeIllustrationSurface[];

export const THEME_ILLUSTRATION_SET_IDS = [
  "none",
  "forest-grove",
  "tidal-grove",
  "desert-dusk",
  "alpine-fog",
  "moonlit-garden",
] as const satisfies readonly ThemeIllustrationSetId[];

type CatalogAsset = {
  assetId: string;
  mimeType: "image/webp" | "image/png";
  width: number;
  height: number;
  sha256: string;
  path: string;
};
type Catalog = {
  schemaVersion: 2;
  sets: Record<string, Record<ThemeIllustrationSurface, CatalogAsset>>;
};

export const THEME_ILLUSTRATION_CATALOG = catalog as unknown as Catalog;

export const DEFAULT_THEME_ILLUSTRATIONS: ThemeIllustrations = {
  opacity: 0,
  surfaces: {
    workbench: false,
    adminCenter: false,
    agentManager: false,
  },
  scenes: {
    workbench: {} as ThemeIllustrationAsset,
    adminCenter: {} as ThemeIllustrationAsset,
    agentManager: {} as ThemeIllustrationAsset,
  },
};

export const THEME_ILLUSTRATION_OPTIONS = [
  { id: "none", label: "无插画" },
  { id: "forest-grove", label: "森林绿插画组" },
  { id: "tidal-grove", label: "潮汐蓝插画组" },
  { id: "desert-dusk", label: "沙漠黄昏插画组" },
  { id: "alpine-fog", label: "高山薄雾插画组" },
  { id: "moonlit-garden", label: "月夜花园插画组" },
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
  setId: ThemeIllustrationSetId,
  surface: ThemeIllustrationSurface,
) {
  return THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface]?.path || "";
}

export function builtinIllustrationAsset(
  setId: ThemeIllustrationSetId,
  surface: ThemeIllustrationSurface,
): ThemeIllustrationAsset {
  const asset = THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface];
  if (!asset) throw new Error(`缺少内置插画资源：${setId}/${surface}`);
  const { path: _path, ...metadata } = asset;
  return { kind: "builtin", ...metadata };
}

export function illustrationAssetResourcePath(asset: ThemeIllustrationAsset) {
  if (asset.kind === "uploaded") {
    return `/api/ui/theme-assets/${encodeURIComponent(asset.assetId)}`;
  }
  for (const setId of THEME_ILLUSTRATION_SET_IDS) {
    for (const surface of THEME_ILLUSTRATION_SURFACES) {
      const candidate = THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface];
      if (candidate?.assetId === asset.assetId) return candidate.path;
    }
  }
  return "";
}

export function illustrationSetIdForAsset(asset: ThemeIllustrationAsset, surface: ThemeIllustrationSurface) {
  if (asset.kind !== "builtin") return "";
  return THEME_ILLUSTRATION_SET_IDS.find((setId) => THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface]?.assetId === asset.assetId) || "";
}

export function defaultIllustrations(): ThemeIllustrations {
  return {
    opacity: DEFAULT_THEME_ILLUSTRATIONS.opacity,
    surfaces: { ...DEFAULT_THEME_ILLUSTRATIONS.surfaces },
    scenes: Object.fromEntries(
      THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, builtinIllustrationAsset("none", surface)]),
    ) as ThemeIllustrations["scenes"],
  };
}
