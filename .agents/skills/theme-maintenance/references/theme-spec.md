# Theme Spec

This document describes the theme contract the current code already implements. The exact tokens, illustration asset IDs, dimensions and hashes are defined by the JSON files in the repository; this document records the structure, the boundaries and the relationships that are easy to miss.

## Theme system boundaries

The current release package contains eight read-only preset themes, with the following order and identities:

| ID | Name | Role | Current illustration set |
| --- | --- | --- | --- |
| `paper-daylight` | Steel Core | Default theme; keep this ID | `armor-core-hud` |
| `theme_0f2e4a8c1d6b4f90a3c7e5b2d8f1046a` | Apollo Plan | Release preset | `apollo-plan` |
| `theme_92ba863d3714c089235dfcef47ce3415` | Mint Citrus | Release preset | `mint-citrus` |
| `theme_43f2d67a91c84f0aa8d5e1c7b3f9264d` | K-On | Release preset | `k-on-light-music` |
| `theme_3dc3829743be9c6941e6da88c0f780a1` | Cyberpunk | Release preset | `cyberpunk-2077` |
| `theme_6f7ac1823da81d2e52d1a1549ee69c85` | Deepseek | Release preset | `deepseek-big-fish` |
| `theme_7b6e1d3a4c5f708192a3b4c5d6e7f809` | Mist Paper | Release preset | `alpine-fog` |
| `theme_8c7d2e4b5a6f8192a3b4c5d6e7f8091a` | Ink Brass | Release preset | `moonlit-garden` |

The table uses the English names from `README.en.md`; the `name` field of each preset in `theme_presets.json` holds the Chinese display name listed in `README.md`.

Every release preset has `schemaVersion: 1`, `baseId: "paper-daylight"` and `readonly: true`. The default theme should stay first in the theme list. When adding a theme, read `bot/web/theme_presets.json` first, and do not treat the count in the table above as a constant that never changes.

The theme library is read through `/api/public/ui/themes` and `/api/ui/themes`. The login page saves its preview selection only in the current browser; the signed-in endpoint returns the selected theme of the current account, and accounts are isolated from each other. The runtime persists the theme library revision and the mapping from account to selected theme ID, with the legacy global selected ID as the migration fallback. The current `bot/web/theme_store.py` and the theme routes reject theme creation, import, update, deletion and asset upload and return a read-only error; the preset content in the theme package is still provided by the versioned files.

## Source files and consumers

| File | Purpose | When to modify |
| --- | --- | --- |
| `bot/web/theme_presets.json` | The released theme manifest and the complete appearance of each theme | Adding or editing a release preset |
| `bot/web/theme_catalog.json` | The color token catalog with `schemaVersion: 1`; currently 299 tokens (`light.glow` is the theme light color, derived from `accent` by default) | Adding/removing tokens, CSS variables or token semantics |
| `bot/web/theme_illustrations.json` | The built-in illustration sets with `schemaVersion: 3`, the three surface types, layer metadata and asset paths | Adding/replacing built-in illustration assets |
| `front/public/assets/theme-illustrations/` | The static assets matching the illustration catalog paths | Adding/replacing built-in illustration files |
| `front/src/theme/resolveAppearance.ts` | Frontend appearance normalization, derived color resolution, illustration resolution and contrast calculation | Only when the theme contract or resolution behavior changes |
| `front/src/theme/types.ts` | The theme structure, surfaces, illustration sets and asset types | When adding a surface or an illustration set type |
| `front/src/theme/illustrationPresets.ts` | Illustration set IDs, display options, templates and the catalog mapping | When adding an illustration set or editing the theme manager options |
| `bot/web/theme_store.py` | Backend validation of tokens, illustrations and theme files, and per-account selection persistence | When the backend contract changes, or a new illustration set must be added to the allowlist |
| `tests/test_theme_store.py`, `tests/test_theme_api.py` | The backend theme data and API contract | When the manifest identity, the read-only boundary or the asset contract changes |
| `front/src/test/theme*.test.ts*` | The frontend resolution, client, illustration and manager contract | When the affected frontend behavior changes |

An ordinary preset theme only needs changes to `theme_presets.json`; when it uses existing tokens and illustration sets, the resolver, the types and the registries do not need to change.

## Theme object

The root shape of the release file is:

```json
{
  "schemaVersion": 1,
  "scope": "global",
  "revision": 0,
  "selectedThemeId": "paper-daylight",
  "themes": [
    {
      "schemaVersion": 1,
      "id": "theme_<32 lowercase hex digits>",
      "name": "Theme name",
      "baseId": "paper-daylight",
      "appearance": {
        "colors": {
          "scheme": "light",
          "overrides": {}
        },
        "typography": {
          "chatBodyFontFamily": "sans",
          "chatBodyFontSize": "medium",
          "chatBodyLineHeight": "normal",
          "chatBodyParagraphSpacing": "normal"
        },
        "material": {
          "shape": "crisp",
          "glass": "frost",
          "glow": "soft",
          "depth": "float"
        },
        "illustrations": {}
      },
      "readonly": true,
      "updatedAt": "2026-01-01T00:00:00Z",
      "version": 1
    }
  ]
}
```

`illustrations` in the example is only a placeholder; a released theme must use the complete normalized scene configuration. A new theme ID should be stable and unique, in the format `theme_` plus 32 lowercase hex digits; `paper-daylight` is the reserved default ID. Do not create a seemingly brand-new theme by renaming or reusing an old ID, or the selections accounts have already saved will point to a different appearance.

After backend validation, `name` must be 1 to 80 characters and must not contain control characters. `updatedAt` must be an ISO time string that includes a timezone, and `version` is an integer of at least 1. The theme `baseId` is currently fixed to `paper-daylight`, and `schemaVersion` is currently fixed to 1.

## Color contract

`appearance.colors` may only contain `scheme` and `overrides`. `scheme` is `light` or `dark`; the keys of `overrides` must come from `theme_catalog.json`.

- Colors accept `#RGB`, `#RGBA`, `#RRGGBB` or `#RRGGBBAA`, and the backend normalizes them to the uppercase eight-digit format.
- A token with `allowAlpha: false` must use a fully opaque color; alpha can be used only when the catalog allows transparency.
- A token not written in `overrides` uses the catalog's `derive` or `default`. The keys a derived token depends on must exist, and circular dependencies are not allowed.
- When `cssVariable` exists, the value is written to the corresponding CSS custom property; a token without `cssVariable` may still be read directly by components and must not be deleted just because it has no CSS variable.
- `contrastAgainst` and `minContrast` describe the minimum contrast target of tokens such as text, focus and borders. After editing colors, check the contrast hints in the theme manager, and cover scenes such as the workbench, chat, editor, terminal, file tree, status feedback and overlays.
- Tokens marked `terminal` generate the terminal theme. At a minimum, check the readability of the terminal foreground, the cursor, and the selection foreground against the selection background; the existing tests use 4.5 as the terminal baseline.

## Typography contract

`appearance.typography` may be omitted; the resolver uses the defaults. If it is provided, all four fields must exist:

- `chatBodyFontFamily`: `sans`, `serif`, `kai`, `fangsong` or `mono`
- `chatBodyFontSize`: `small`, `medium` or `large`
- `chatBodyLineHeight`: `tight`, `normal` or `relaxed`
- `chatBodyParagraphSpacing`: `tight`, `normal` or `relaxed`

All eight currently released themes store the default typography values explicitly. Keep these four items complete when editing a theme, to avoid a half configuration that depends on implicit defaults.

## Material contract

`appearance.material` describes the non-color texture of a theme and may be omitted (the resolver uses `crisp/frost/soft/float`). If it is provided, all four fields must exist:

- `shape`: `sharp`, `crisp`, `soft` or `round`; determines `--radius-control/chip/card/panel/overlay/bubble`
- `glass`: `none`, `frost` or `deep`; determines the blur, saturation and opacity of glass panels (`--glass-*`); `none` is an opaque paper surface
- `glow`: `none`, `soft` or `vivid`; determines `--glow-strength`; `none` also turns off light-effect animations such as the sweep and the breathing light
- `depth`: `flat`, `print` or `float`; determines `--shadow-island/raised/overlay`; `print` uses solid offset shadows

`front/src/theme/material.ts` resolves the material into CSS variables and writes `data-material-*` attributes on the root node; the backend `theme_store.py` validates the same enums. The design system primitives (island panels, buttons, segmented controls, cover banners and so on) are in `front/src/styles/orbit.css`; they only consume these variables and do not hard-code corner radii, shadows or light effects. All eight released themes store the complete material explicitly.

## Illustration contract

A new released theme uses the normalized `appearance.illustrations`:

```json
{
  "opacity": 0.12,
  "surfaces": {
    "workbench": true,
    "adminCenter": true,
    "agentManager": true
  },
  "scenes": {
    "workbench": { "layers": [] },
    "adminCenter": { "layers": [] },
    "agentManager": { "layers": [] }
  }
}
```

The only current surfaces are `workbench`, `adminCenter` and `agentManager`, and all three must be present. Each scene contains 1 to 32 layers, and layer IDs are unique within the scene. A layer requires `id`, `asset`, `anchor` and `enabled`; `anchor` is `top`, `left`, `right`, `bottom`, `bottom-left`, `bottom-right` or `center`. The optional `x` and `y` range from -100 to 100, `width` and `height` from 0.01 to 300, `opacity` from 0 to 1, and `objectPosition` is at most 120 characters. The overall scene `opacity` ranges from 0 to 1; the new UI uses illustrations as full-strength canvases and covers, release presets are usually 1, and the readability of text areas is the responsibility of the glass panels.

Built-in assets must come from `theme_illustrations.json` and fully match its `assetId`, `mimeType`, `width`, `height` and `sha256`. The asset path must correspond to an actual file under `front/public/assets/`. Uploaded assets are additionally limited to 4 MiB per file and 12 MiB in total per theme; a release preset should not write uploaded assets into the theme file.

The current illustration catalog has twelve sets: `none`, `forest-grove`, `tidal-grove`, `desert-dusk`, `alpine-fog`, `moonlit-garden`, `armor-core-hud`, `apollo-plan`, `mint-citrus`, `cyberpunk-2077`, `deepseek-big-fish` and `k-on-light-music`. `none` is the undecorated baseline. The illustration catalog must stay in sync with the backend allowlist, the frontend `ThemeIllustrationSetId` union type and the options array.

The legacy `setId`/`upload` format is still used for import and migration. New release data uses the `scenes` spec; do not add the legacy format unless the task itself is maintaining migration compatibility.
