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

export type ThemeIllustrationSurface =
  | "workbench"
  | "adminCenter"
  | "agentManager";

export type ThemeIllustrationLegacySurface =
  | "workbench"
  | "chat"
  | "topbar"
  | "management";

export type ThemeIllustrationSetId =
  | "none"
  | "forest-grove"
  | "tidal-grove"
  | "desert-dusk"
  | "alpine-fog"
  | "moonlit-garden"
  | "armor-core-hud";

export type ThemeIllustrationUploadMime = "image/png" | "image/jpeg" | "image/webp";

export type ThemeIllustrationBuiltinAsset = {
  kind: "builtin";
  assetId: string;
  mimeType: "image/webp" | "image/png";
  width: number;
  height: number;
  sha256: string;
};

export type ThemeIllustrationUploadedAsset = {
  kind: "uploaded";
  assetId: string;
  mimeType: ThemeIllustrationUploadMime;
  width: number;
  height: number;
  sha256: string;
};

export type ThemeIllustrationAsset =
  | ThemeIllustrationBuiltinAsset
  | ThemeIllustrationUploadedAsset;

export type ThemeIllustrationAnchor =
  | "top"
  | "left"
  | "right"
  | "bottom"
  | "bottom-left"
  | "bottom-right"
  | "center";

export type ThemeIllustrationLayerSpec = {
  id: string;
  asset: ThemeIllustrationAsset;
  anchor: ThemeIllustrationAnchor;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  objectPosition?: string;
  opacity?: number;
  enabled: boolean;
};

export type ThemeIllustrationScene = {
  layers: ThemeIllustrationLayerSpec[];
};

export type ThemeIllustrationUpload = {
  mimeType: ThemeIllustrationUploadMime;
  data: string;
};

export type LegacyThemeIllustrations = {
  setId: ThemeIllustrationSetId | "upload";
  upload?: ThemeIllustrationUpload;
  opacity: number;
  surfaces: Record<ThemeIllustrationLegacySurface, boolean>;
};

export type ThemeIllustrationAssetImport = {
  assetId: string;
  mimeType: ThemeIllustrationUploadMime;
  data: string;
};

export type ThemeIllustrations = {
  opacity: number;
  surfaces: Record<ThemeIllustrationSurface, boolean>;
  scenes: Record<ThemeIllustrationSurface, ThemeIllustrationScene>;
};

export type ThemeIllustrationsValue = ThemeIllustrations | LegacyThemeIllustrations;

export const PAPER_STYLE = { fileTreeRowHeight: 26 } as const;
export const PAPER_MOTION = { profile: "paper" } as const;

export type ThemeAppearance = {
  colors: { scheme: ColorScheme; overrides: Record<string, string> };
  typography?: ChatTypography;
  illustrations?: ThemeIllustrationsValue;
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

export type PortableTheme = Pick<UiTheme, "schemaVersion" | "name" | "baseId" | "appearance">;
export type ThemeDocument = PortableTheme | { schemaVersion: 1; themes: PortableTheme[] };
export type ThemeImportInput = {
  expectedRevision: number;
  document: unknown;
  assets?: ThemeIllustrationAssetImport[];
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
  illustrations: ThemeIllustrations & {
    resources: Record<ThemeIllustrationSurface, string>;
    sceneResources: Record<ThemeIllustrationSurface, string[]>;
    /** @deprecated Only exposed while reading legacy themes. */
    setId?: ThemeIllustrationSetId | "upload";
  };
  revision: string;
};
