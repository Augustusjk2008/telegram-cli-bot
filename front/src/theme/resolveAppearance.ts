import catalog from "../../../bot/web/theme_catalog.json";
import presetCatalog from "../../../bot/web/theme_presets.json";
import type {
  ColorToken,
  LegacyThemeIllustrations,
  ThemeIllustrationAsset,
  ThemeIllustrationAnchor,
  ThemeIllustrationLayerSpec,
  ThemeIllustrationScene,
  ThemeIllustrationSurface,
  ThemeIllustrationUpload,
  ThemeIllustrationUploadMime,
  ThemeIllustrations,
  ThemeIllustrationsValue,
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
import { DEFAULT_THEME_MATERIAL, isThemeMaterial, materialCssVariables, normalizeThemeMaterial } from "./material";
import {
  builtinIllustrationScene,
  defaultIllustrations,
  illustrationAssetResourcePath,
  legacyIllustrationSetIdForAssetId,
  THEME_ILLUSTRATION_SET_IDS,
  THEME_ILLUSTRATION_SURFACES,
  THEME_ILLUSTRATION_CATALOG,
} from "./illustrationPresets";

export const THEME_TOKENS = catalog.tokens as ColorToken[];
export const MAX_THEME_ILLUSTRATION_UPLOAD_BYTES = 4 * 1024 * 1024;
export const MAX_THEME_ILLUSTRATION_TOTAL_BYTES = 12 * 1024 * 1024;
export const MAX_THEME_ILLUSTRATION_OPACITY = 1;
const APPEARANCE_KEYS = ["colors", "typography", "material", "illustrations"];
const THEME_ILLUSTRATION_UPLOAD_MIMES = ["image/png", "image/jpeg", "image/webp"] as const satisfies readonly ThemeIllustrationUploadMime[];
const THEME_ILLUSTRATION_DATA_URL = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$/;
const ASSET_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;
const SHA256 = /^[a-f0-9]{64}$/i;

const PRESET_LIBRARY = presetCatalog as unknown as ThemeLibrary;
export const BUILTIN_THEME: UiTheme = PRESET_LIBRARY.themes.find((theme) => theme.id === "paper-daylight") || {
  schemaVersion: 1,
  id: "paper-daylight",
  name: "钢铁核心",
  baseId: "paper-daylight",
  appearance: {
    colors: { scheme: "light", overrides: {} },
    typography: DEFAULT_CHAT_TYPOGRAPHY,
    material: DEFAULT_THEME_MATERIAL,
    illustrations: defaultIllustrations(),
  },
  readonly: true,
  updatedAt: "",
  version: 1,
};

export function builtinLibrary(): ThemeLibrary {
  return JSON.parse(JSON.stringify(PRESET_LIBRARY)) as ThemeLibrary;
}
export function normalizeColor(value: string, allowAlpha = true): string | null {
  let hex = value.trim().toUpperCase();
  if (!/^#(?:[0-9A-F]{3}|[0-9A-F]{4}|[0-9A-F]{6}|[0-9A-F]{8})$/.test(hex)) return null;
  if (hex.length === 4 || hex.length === 5) hex = `#${[...hex.slice(1)].map((c) => c + c).join("")}`;
  if (hex.length === 7) hex += "FF";
  return allowAlpha || hex.endsWith("FF") ? hex : null;
}

function uploadBytes(upload: ThemeIllustrationUpload) {
  const match = THEME_ILLUSTRATION_DATA_URL.exec(upload.data);
  if (!match || match[1] !== upload.mimeType) throw new Error("上传插画数据无效");
  const payload = match[2];
  const estimatedBytes = Math.floor(payload.length * 3 / 4) - (payload.endsWith("==") ? 2 : payload.endsWith("=") ? 1 : 0);
  if (estimatedBytes <= 0 || estimatedBytes > MAX_THEME_ILLUSTRATION_UPLOAD_BYTES) {
    throw new Error("上传插画不能超过 4 MiB");
  }
  if (typeof atob !== "function") return null;
  let binary: string;
  try { binary = atob(payload); }
  catch { throw new Error("上传插画数据无效"); }
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  const validSignature = upload.mimeType === "image/png"
    ? bytes.length >= 8 && bytes.slice(0, 8).every((value, index) => value === [137, 80, 78, 71, 13, 10, 26, 10][index])
    : upload.mimeType === "image/jpeg"
      ? bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
      : bytes.length >= 12 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46
        && bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50;
  if (!validSignature) throw new Error("上传插画文件内容与类型不匹配");
  return bytes;
}

export function normalizeIllustrationUpload(value: unknown): ThemeIllustrationUpload {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("上传插画配置无效");
  const candidate = value as Record<string, unknown>;
  if (Object.keys(candidate).some((key) => !["mimeType", "data"].includes(key))) {
    throw new Error("上传插画配置包含不支持的字段");
  }
  if (!THEME_ILLUSTRATION_UPLOAD_MIMES.includes(candidate.mimeType as ThemeIllustrationUploadMime)) {
    throw new Error("上传插画格式只支持 PNG、JPEG 或 WebP");
  }
  if (typeof candidate.data !== "string") throw new Error("上传插画数据无效");
  const upload = { mimeType: candidate.mimeType as ThemeIllustrationUploadMime, data: candidate.data };
  uploadBytes(upload);
  return upload;
}

function shortHash(value: string) {
  let first = 0x811c9dc5;
  let second = 0x01000193;
  for (const char of value) {
    first = Math.imul(first ^ char.charCodeAt(0), 16777619);
    second = Math.imul(second ^ char.charCodeAt(0), 2246822519);
  }
  return `${(first >>> 0).toString(16).padStart(8, "0")}${(second >>> 0).toString(16).padStart(8, "0")}`.repeat(4).slice(0, 64);
}

function legacyAsset(upload: ThemeIllustrationUpload): ThemeIllustrationAsset {
  const hash = shortHash(upload.data);
  return {
    kind: "uploaded",
    assetId: `legacy-${hash}`,
    mimeType: upload.mimeType,
    width: 0,
    height: 0,
    sha256: hash,
  };
}

function normalizeAsset(value: unknown): ThemeIllustrationAsset {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("场景插画资源无效");
  const candidate = value as Record<string, unknown>;
  if (Object.keys(candidate).some((key) => !["kind", "assetId", "mimeType", "width", "height", "sha256"].includes(key))) {
    throw new Error("场景插画资源包含不支持的字段");
  }
  if (candidate.kind !== "builtin" && candidate.kind !== "uploaded") throw new Error("场景插画资源类型无效");
  if (typeof candidate.assetId !== "string" || !ASSET_ID.test(candidate.assetId)) throw new Error("场景插画资源 ID 无效");
  const mimeTypeIsValid = candidate.kind === "builtin"
    ? candidate.mimeType === "image/png" || candidate.mimeType === "image/webp"
    : THEME_ILLUSTRATION_UPLOAD_MIMES.includes(candidate.mimeType as ThemeIllustrationUploadMime);
  if (!mimeTypeIsValid) throw new Error("场景插画 MIME 无效");
  if (!Number.isInteger(candidate.width) || !Number.isInteger(candidate.height)
    || Number(candidate.width) < 1 || Number(candidate.height) < 1) throw new Error("场景插画尺寸无效");
  if (typeof candidate.sha256 !== "string" || !SHA256.test(candidate.sha256)) throw new Error("场景插画哈希无效");
  const asset = {
    kind: candidate.kind,
    assetId: candidate.assetId,
    mimeType: candidate.mimeType,
    width: candidate.width,
    height: candidate.height,
    sha256: candidate.sha256.toLowerCase(),
  } as ThemeIllustrationAsset;
  if (asset.kind === "builtin") {
    const catalogAsset = Object.values(THEME_ILLUSTRATION_CATALOG.sets)
      .flatMap((set) => Object.values(set).flatMap((scene) => scene.layers.map((layer) => layer.asset)))
      .find((item) => item.assetId === asset.assetId);
    if (!catalogAsset || catalogAsset.mimeType !== asset.mimeType || catalogAsset.width !== asset.width
      || catalogAsset.height !== asset.height || catalogAsset.sha256 !== asset.sha256) {
      throw new Error("内置场景插画元数据无效");
    }
  }
  return asset;
}

const ILLUSTRATION_ANCHORS = ["top", "left", "right", "bottom", "bottom-left", "bottom-right", "center"] as const satisfies readonly ThemeIllustrationAnchor[];
const LAYER_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;

function normalizeLayer(value: unknown, surface: ThemeIllustrationSurface, index: number): ThemeIllustrationLayerSpec {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`主题插画图层无效：${surface}/${index}`);
  const candidate = value as Record<string, unknown>;
  const allowed = ["id", "asset", "anchor", "x", "y", "width", "height", "objectPosition", "opacity", "enabled"];
  if (Object.keys(candidate).some((key) => !allowed.includes(key))) throw new Error(`主题插画图层包含不支持的字段：${surface}/${index}`);
  if (typeof candidate.id !== "string" || !LAYER_ID.test(candidate.id)) throw new Error(`主题插画图层 ID 无效：${surface}/${index}`);
  if (!ILLUSTRATION_ANCHORS.includes(candidate.anchor as ThemeIllustrationAnchor)) throw new Error(`主题插画图层锚点无效：${surface}/${index}`);
  if (typeof candidate.enabled !== "boolean") throw new Error(`主题插画图层启用状态无效：${surface}/${index}`);
  const finitePercent = (key: string, min: number, max: number) => {
    if (candidate[key] === undefined) return undefined;
    if (typeof candidate[key] !== "number" || !Number.isFinite(candidate[key]) || candidate[key] < min || candidate[key] > max) {
      throw new Error(`主题插画图层${key}无效：${surface}/${index}`);
    }
    return candidate[key];
  };
  const x = finitePercent("x", -100, 100);
  const y = finitePercent("y", -100, 100);
  const width = finitePercent("width", 0.01, 300);
  const height = finitePercent("height", 0.01, 300);
  const opacity = finitePercent("opacity", 0, 1);
  const objectPosition = candidate.objectPosition;
  if (objectPosition !== undefined && (typeof objectPosition !== "string" || objectPosition.length > 120)) {
    throw new Error(`主题插画图层 objectPosition 无效：${surface}/${index}`);
  }
  return {
    id: candidate.id,
    asset: normalizeAsset(candidate.asset),
    anchor: candidate.anchor as ThemeIllustrationAnchor,
    ...(x === undefined ? {} : { x }),
    ...(y === undefined ? {} : { y }),
    ...(width === undefined ? {} : { width }),
    ...(height === undefined ? {} : { height }),
    ...(objectPosition === undefined ? {} : { objectPosition: objectPosition as string }),
    ...(opacity === undefined ? {} : { opacity }),
    enabled: candidate.enabled,
  };
}

function sceneFromAsset(asset: ThemeIllustrationAsset, id: string): ThemeIllustrationScene {
  return {
    layers: [{
      id,
      asset,
      anchor: "center",
      width: 100,
      height: 100,
      objectPosition: "50% 50%",
      enabled: true,
    }],
  };
}

function normalizeScene(value: unknown, surface: ThemeIllustrationSurface): ThemeIllustrationScene {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`主题插画场景无效：${surface}`);
  const candidate = value as Record<string, unknown>;
  if (!Object.hasOwn(candidate, "layers")) {
    const legacySetId = candidate.kind === "builtin" && typeof candidate.assetId === "string"
      ? legacyIllustrationSetIdForAssetId(candidate.assetId, surface)
      : "";
    if (legacySetId) return builtinIllustrationScene(legacySetId as typeof THEME_ILLUSTRATION_SET_IDS[number], surface);
    return sceneFromAsset(normalizeAsset(value), `${surface}-layer`);
  }
  if (Object.keys(candidate).some((key) => key !== "layers") || !Array.isArray(candidate.layers) || candidate.layers.length < 1 || candidate.layers.length > 32) {
    throw new Error(`主题插画图层列表无效：${surface}`);
  }
  if (candidate.layers.length === 1) {
    const firstLayer = candidate.layers[0];
    const firstAsset = firstLayer && typeof firstLayer === "object" && !Array.isArray(firstLayer)
      ? (firstLayer as Record<string, unknown>).asset
      : undefined;
    const legacySetId = firstAsset && typeof firstAsset === "object" && !Array.isArray(firstAsset)
      && (firstAsset as Record<string, unknown>).kind === "builtin"
      && typeof (firstAsset as Record<string, unknown>).assetId === "string"
      ? legacyIllustrationSetIdForAssetId((firstAsset as Record<string, unknown>).assetId as string, surface)
      : "";
    if (legacySetId) return builtinIllustrationScene(legacySetId as typeof THEME_ILLUSTRATION_SET_IDS[number], surface);
  }
  const layers = candidate.layers.map((layer, index) => normalizeLayer(layer, surface, index));
  const ids = new Set<string>();
  if (layers.some((layer) => ids.has(layer.id) || !ids.add(layer.id))) throw new Error(`主题插画图层 ID 重复：${surface}`);
  return { layers };
}

function isLegacy(value: unknown): value is LegacyThemeIllustrations {
  return Boolean(value && typeof value === "object" && !Array.isArray(value) && "setId" in value);
}

function canonicalFromLegacy(value: LegacyThemeIllustrations): ThemeIllustrations {
  const candidate = value as unknown as Record<string, unknown>;
  if (Object.keys(candidate).some((key) => !["setId", "upload", "opacity", "surfaces"].includes(key))) {
    throw new Error("主题插画配置包含不支持的字段");
  }
  if (!THEME_ILLUSTRATION_SET_IDS.includes(value.setId as typeof THEME_ILLUSTRATION_SET_IDS[number]) && value.setId !== "upload") {
    throw new Error("主题插画资源无效");
  }
  const upload = value.upload === undefined ? undefined : normalizeIllustrationUpload(value.upload);
  if ((value.setId === "upload") !== Boolean(upload)) throw new Error("上传插画配置与资源类型不匹配");
  const surfaces = value.surfaces as Record<string, unknown>;
  if (!surfaces || typeof surfaces !== "object" || Array.isArray(surfaces)
    || Object.keys(surfaces).some((key) => !["workbench", "chat", "topbar", "management"].includes(key))
    || ["workbench", "chat", "topbar", "management"].some((surface) => typeof surfaces[surface] !== "boolean")) {
    throw new Error("主题插画区域配置无效");
  }
  const asset = upload ? legacyAsset(upload) : null;
  const setId = value.setId === "upload" ? "none" : value.setId;
  return {
    opacity: value.opacity,
    surfaces: {
      workbench: Boolean(surfaces.workbench || surfaces.chat || surfaces.topbar),
      adminCenter: Boolean(surfaces.management),
      agentManager: Boolean(surfaces.management),
    },
    scenes: Object.fromEntries(THEME_ILLUSTRATION_SURFACES.map((surface) => [
      surface,
      asset
        ? sceneFromAsset(asset, `${surface}-legacy`)
        : builtinIllustrationScene(setId as typeof THEME_ILLUSTRATION_SET_IDS[number], surface),
    ])) as ThemeIllustrations["scenes"],
  };
}

export function normalizeIllustrations(value: unknown): ThemeIllustrations {
  if (value === undefined) return defaultIllustrations();
  if (isLegacy(value)) {
    const normalized = canonicalFromLegacy(value);
    if (typeof normalized.opacity !== "number" || !Number.isFinite(normalized.opacity)
      || normalized.opacity < 0 || normalized.opacity > MAX_THEME_ILLUSTRATION_OPACITY) throw new Error("主题插画透明度必须在 0 到 1 之间");
    return normalized;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("主题插画配置无效");
  const candidate = value as Record<string, unknown>;
  if (Object.keys(candidate).some((key) => !["opacity", "surfaces", "scenes"].includes(key))) {
    throw new Error("主题插画配置包含不支持的字段");
  }
  if (typeof candidate.opacity !== "number" || !Number.isFinite(candidate.opacity) || candidate.opacity < 0 || candidate.opacity > MAX_THEME_ILLUSTRATION_OPACITY) {
    throw new Error("主题插画透明度必须在 0 到 1 之间");
  }
  const surfaces = candidate.surfaces;
  if (!surfaces || typeof surfaces !== "object" || Array.isArray(surfaces)) throw new Error("主题插画区域配置无效");
  const surfaceRecord = surfaces as Record<string, unknown>;
  if (Object.keys(surfaceRecord).some((key) => !THEME_ILLUSTRATION_SURFACES.includes(key as ThemeIllustrationSurface))
    || THEME_ILLUSTRATION_SURFACES.some((surface) => typeof surfaceRecord[surface] !== "boolean")) {
    throw new Error("主题插画区域配置无效");
  }
  const scenes = candidate.scenes;
  if (!scenes || typeof scenes !== "object" || Array.isArray(scenes)) throw new Error("主题插画场景配置无效");
  const sceneRecord = scenes as Record<string, unknown>;
  if (Object.keys(sceneRecord).some((key) => !THEME_ILLUSTRATION_SURFACES.includes(key as ThemeIllustrationSurface))
    || THEME_ILLUSTRATION_SURFACES.some((surface) => sceneRecord[surface] === undefined)) {
    throw new Error("主题插画场景配置无效");
  }
  return {
    opacity: candidate.opacity,
    surfaces: Object.fromEntries(THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, surfaceRecord[surface] as boolean])) as ThemeIllustrations["surfaces"],
    scenes: Object.fromEntries(THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, normalizeScene(sceneRecord[surface], surface)])) as ThemeIllustrations["scenes"],
  };
}

function legacyUploadData(value: ThemeIllustrationsValue) {
  return isLegacy(value) && value.setId === "upload" && value.upload
    ? normalizeIllustrationUpload(value.upload).data
    : "";
}

export function resolveAppearance(theme: UiTheme): ResolvedAppearance {
  if (theme.schemaVersion !== 1) throw new Error("此主题使用了尚不支持的数据版本");
  const colors: Record<string, string> = {};
  const cssVariables: Record<string, string> = {};
  const tokens = new Map(THEME_TOKENS.map((token) => [token.key, token]));
  if (!theme.appearance || Object.keys(theme.appearance).some((key) => !APPEARANCE_KEYS.includes(key))
    || !theme.appearance.colors || !["light", "dark"].includes(theme.appearance.colors.scheme)
    || Object.keys(theme.appearance.colors).some((key) => key !== "scheme" && key !== "overrides")
    || !theme.appearance.colors.overrides || typeof theme.appearance.colors.overrides !== "object"
    || Array.isArray(theme.appearance.colors.overrides)
    || (theme.appearance.typography !== undefined && !isChatTypography(theme.appearance.typography))
    || (theme.appearance.material !== undefined && !isThemeMaterial(theme.appearance.material))) throw new Error("此主题包含尚不支持的外观配置");
  const rawIllustrations = theme.appearance.illustrations;
  const illustrations = normalizeIllustrations(rawIllustrations);
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
  const material = normalizeThemeMaterial(theme.appearance.material);
  Object.assign(cssVariables, materialCssVariables(material));
  const legacyData = legacyUploadData(rawIllustrations as ThemeIllustrationsValue);
  const sceneResources = Object.fromEntries(
    THEME_ILLUSTRATION_SURFACES.map((surface) => [
      surface,
      illustrations.scenes[surface].layers.map((layer) => (
        legacyData || illustrationAssetResourcePath(layer.asset)
      )),
    ]),
  ) as Record<ThemeIllustrationSurface, string[]>;
  const resources = Object.fromEntries(
    THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, sceneResources[surface][0] || ""]),
  ) as Record<ThemeIllustrationSurface, string>;
  const legacySetId = isLegacy(rawIllustrations) ? rawIllustrations.setId : undefined;
  const resolvedIllustrations = {
    ...illustrations,
    resources,
    sceneResources,
    ...(legacySetId ? { setId: legacySetId } : {}),
  } as ResolvedAppearance["illustrations"];
  const revision = JSON.stringify([theme.id, theme.appearance.colors.scheme, colors, typography, material, resolvedIllustrations]);
  return { themeId: theme.id, scheme: theme.appearance.colors.scheme, typography, material, colors, cssVariables, styleProfile: "paper", motionProfile: "paper", style: PAPER_STYLE, motion: PAPER_MOTION, illustrations: resolvedIllustrations, revision };
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
