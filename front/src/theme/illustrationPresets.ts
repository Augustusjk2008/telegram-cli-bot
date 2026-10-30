import type {
  ThemeIllustrationAsset,
  ThemeIllustrationLayerSpec,
  ThemeIllustrationSetId,
  ThemeIllustrationScene,
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

const LEGACY_SURFACE_FILENAMES: Record<ThemeIllustrationSurface, string> = {
  workbench: "workbench",
  adminCenter: "admin-center",
  agentManager: "agent-manager",
};

type CatalogAsset = {
  assetId: string;
  mimeType: "image/webp" | "image/png";
  width: number;
  height: number;
  sha256: string;
  path: string;
};
type CatalogLayer = Omit<ThemeIllustrationLayerSpec, "asset"> & {
  asset: CatalogAsset;
};
type CatalogScene = {
  layers: CatalogLayer[];
};
type Catalog = {
  schemaVersion: 3;
  sets: Record<string, Record<ThemeIllustrationSurface, CatalogScene>>;
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
    workbench: {} as ThemeIllustrationScene,
    adminCenter: {} as ThemeIllustrationScene,
    agentManager: {} as ThemeIllustrationScene,
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
  return THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface]?.layers[0]?.asset.path || "";
}

function catalogLayerToAsset(layer: CatalogLayer): ThemeIllustrationAsset {
  const { path: _path, ...metadata } = layer.asset;
  return { kind: "builtin", ...metadata };
}

export function builtinIllustrationScene(
  setId: ThemeIllustrationSetId,
  surface: ThemeIllustrationSurface,
): ThemeIllustrationScene {
  const scene = THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface];
  if (!scene) throw new Error(`缺少内置插画资源：${setId}/${surface}`);
  return {
    layers: scene.layers.map((layer) => ({
      ...layer,
      asset: catalogLayerToAsset(layer),
    })),
  };
}

export function builtinIllustrationAsset(
  setId: ThemeIllustrationSetId,
  surface: ThemeIllustrationSurface,
): ThemeIllustrationAsset {
  return builtinIllustrationScene(setId, surface).layers[0].asset;
}

export function illustrationAssetResourcePath(asset: ThemeIllustrationAsset) {
  if (asset.kind === "uploaded") {
    return `/api/ui/theme-assets/${encodeURIComponent(asset.assetId)}`;
  }
  for (const setId of THEME_ILLUSTRATION_SET_IDS) {
    for (const surface of THEME_ILLUSTRATION_SURFACES) {
      const candidate = THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface]?.layers
        .find((layer) => layer.asset.assetId === asset.assetId);
      if (candidate) return candidate.asset.path;
    }
  }
  return "";
}

export function illustrationSetIdForAsset(asset: ThemeIllustrationAsset, surface: ThemeIllustrationSurface) {
  if (asset.kind !== "builtin") return "";
  return THEME_ILLUSTRATION_SET_IDS.find((setId) => THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface]?.layers
    .some((layer) => layer.asset.assetId === asset.assetId)) || "";
}

export function legacyIllustrationSetIdForAssetId(assetId: string, surface: ThemeIllustrationSurface) {
  const suffix = `-${LEGACY_SURFACE_FILENAMES[surface]}`;
  return THEME_ILLUSTRATION_SET_IDS.find((setId) => assetId === `${setId}${suffix}`) || "";
}

export function illustrationSetIdForScene(scene: ThemeIllustrationScene, surface: ThemeIllustrationSurface) {
  if (!scene.layers.length) return "";
  return THEME_ILLUSTRATION_SET_IDS.find((setId) => {
    const candidate = THEME_ILLUSTRATION_CATALOG.sets[setId]?.[surface]?.layers;
    return Boolean(candidate)
      && candidate.length === scene.layers.length
      && candidate.every((layer, index) => layer.asset.assetId === scene.layers[index]?.asset.assetId);
  }) || "";
}

type DisplayIllustrationLayer = {
  layer: ThemeIllustrationLayerSpec;
  index: number;
  resource: string;
};

const FOREST_GROVE_DISPLAY_RESOURCES: Record<ThemeIllustrationSurface, string> = {
  workbench: "/assets/theme-illustrations/forest-grove/workbench/background.webp",
  adminCenter: "/assets/theme-illustrations/forest-grove/admin-center/background.webp",
  agentManager: "/assets/theme-illustrations/forest-grove/agent-manager/background.webp",
};

function displayLayer(
  source: ThemeIllustrationLayerSpec,
  id: string,
  patch: Partial<ThemeIllustrationLayerSpec>,
  resource: string,
  index: number,
): DisplayIllustrationLayer {
  return {
    layer: { ...source, ...patch, id },
    index,
    resource,
  };
}

export function displayIllustrationLayers(
  scene: ThemeIllustrationScene,
  surface: ThemeIllustrationSurface,
  resources: string[],
): DisplayIllustrationLayer[] {
  const setId = illustrationSetIdForScene(scene, surface);
  if (setId !== "forest-grove") {
    return scene.layers.map((layer, index) => ({
      layer,
      index,
      resource: resources[index] || illustrationAssetResourcePath(layer.asset),
    }));
  }

  const forestResource = FOREST_GROVE_DISPLAY_RESOURCES[surface];
  if (surface === "workbench") {
    const backgroundSource = scene.layers.find((layer) => layer.id !== "top-canopy") || scene.layers[0];
    const leftSource = scene.layers.find((layer) => layer.id === "left-edge-foliage");
    const layers: DisplayIllustrationLayer[] = [];
    if (backgroundSource) {
      layers.push(displayLayer(
        backgroundSource,
        "workbench-background",
        {
          anchor: "center",
          x: 0,
          y: 0,
          width: 100,
          height: 100,
          objectPosition: "50% 50%",
          opacity: 1,
          enabled: scene.layers.some((layer) => layer.id !== "top-canopy" && layer.enabled),
        },
        forestResource,
        0,
      ));
    }
    if (leftSource) {
      layers.push(displayLayer(
        leftSource,
        "left-edge-foliage",
        { opacity: 1 },
        resources[scene.layers.indexOf(leftSource)] || illustrationAssetResourcePath(leftSource.asset),
        1,
      ));
    }
    return layers;
  }

  const source = scene.layers[0];
  return source
    ? [displayLayer(source, `${surface}-background`, {
      anchor: "center",
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      objectPosition: "50% 50%",
      opacity: 1,
      enabled: scene.layers.some((layer) => layer.enabled),
    }, forestResource, 0)]
    : [];
}

export function defaultIllustrations(): ThemeIllustrations {
  return {
    opacity: DEFAULT_THEME_ILLUSTRATIONS.opacity,
    surfaces: { ...DEFAULT_THEME_ILLUSTRATIONS.surfaces },
    scenes: Object.fromEntries(
      THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, builtinIllustrationScene("none", surface)]),
    ) as ThemeIllustrations["scenes"],
  };
}
