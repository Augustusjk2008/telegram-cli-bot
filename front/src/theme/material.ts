import type { ThemeMaterial } from "./types";

/**
 * Theme material: the non-color part of a theme's feel.
 * shape → corner radii, glass → panel translucency and blur,
 * glow → strength of focus/running light effects, depth → shadow language.
 */
export const THEME_MATERIAL_VALUES = {
  shape: ["sharp", "crisp", "soft", "round"],
  glass: ["none", "frost", "deep"],
  glow: ["none", "soft", "vivid"],
  depth: ["flat", "print", "float"],
} as const satisfies { [Key in keyof ThemeMaterial]: readonly ThemeMaterial[Key][] };

export const DEFAULT_THEME_MATERIAL: ThemeMaterial = {
  shape: "crisp",
  glass: "frost",
  glow: "soft",
  depth: "float",
};

const MATERIAL_KEYS = Object.keys(THEME_MATERIAL_VALUES) as Array<keyof ThemeMaterial>;

export function isThemeMaterial(value: unknown): value is ThemeMaterial {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  const keys = Object.keys(candidate);
  return keys.length === MATERIAL_KEYS.length
    && MATERIAL_KEYS.every((key) => (THEME_MATERIAL_VALUES[key] as readonly unknown[]).includes(candidate[key]));
}

export function normalizeThemeMaterial(value: unknown): ThemeMaterial {
  return isThemeMaterial(value) ? { ...value } : { ...DEFAULT_THEME_MATERIAL };
}

const SHAPE_RADII: Record<ThemeMaterial["shape"], Record<string, string>> = {
  sharp: { control: "3px", chip: "3px", card: "4px", panel: "4px", overlay: "6px", bubble: "4px" },
  crisp: { control: "6px", chip: "6px", card: "8px", panel: "10px", overlay: "12px", bubble: "12px" },
  soft: { control: "8px", chip: "8px", card: "12px", panel: "14px", overlay: "16px", bubble: "16px" },
  round: { control: "10px", chip: "999px", card: "14px", panel: "18px", overlay: "20px", bubble: "20px" },
};

const GLASS: Record<ThemeMaterial["glass"], { blur: string; saturate: string; tint: string; tintStrong: string }> = {
  none: { blur: "0px", saturate: "1", tint: "100%", tintStrong: "100%" },
  frost: { blur: "18px", saturate: "1.2", tint: "82%", tintStrong: "90%" },
  deep: { blur: "30px", saturate: "1.35", tint: "70%", tintStrong: "84%" },
};

const GLOW_STRENGTH: Record<ThemeMaterial["glow"], string> = { none: "0", soft: "0.55", vivid: "1" };

const DEPTH_SHADOWS: Record<ThemeMaterial["depth"], Record<string, string>> = {
  flat: {
    island: "0 0 0 0 transparent",
    raised: "0 1px 0 var(--shadow-control-color)",
    overlay: "0 18px 48px -16px var(--shadow-elevated-color)",
  },
  print: {
    island: "3px 3px 0 0 var(--shadow-elevated-color)",
    raised: "2px 2px 0 0 var(--shadow-elevated-color)",
    overlay: "5px 5px 0 0 var(--shadow-elevated-color)",
  },
  float: {
    island: "0 1px 2px var(--shadow-soft-color), 0 14px 36px -12px var(--shadow-elevated-color)",
    raised: "0 1px 2px var(--shadow-soft-color), 0 6px 16px -6px var(--shadow-elevated-color)",
    overlay: "0 2px 6px var(--shadow-soft-color), 0 28px 72px -18px var(--shadow-elevated-color)",
  },
};

export function materialCssVariables(material: ThemeMaterial): Record<string, string> {
  const radii = SHAPE_RADII[material.shape];
  const glass = GLASS[material.glass];
  const shadows = DEPTH_SHADOWS[material.depth];
  return {
    "--radius-control": radii.control,
    "--radius-chip": radii.chip,
    "--radius-card": radii.card,
    "--radius-panel": radii.panel,
    "--radius-overlay": radii.overlay,
    "--radius-bubble": radii.bubble,
    "--radius-sm": radii.control,
    "--radius-md": radii.card,
    "--radius-lg": radii.overlay,
    "--radius-xl": radii.overlay,
    "--glass-blur": glass.blur,
    "--glass-saturate": glass.saturate,
    "--glass-tint": glass.tint,
    "--glass-tint-strong": glass.tintStrong,
    "--glow-strength": GLOW_STRENGTH[material.glow],
    "--shadow-island": shadows.island,
    "--shadow-raised": shadows.raised,
    "--shadow-overlay": shadows.overlay,
  };
}
