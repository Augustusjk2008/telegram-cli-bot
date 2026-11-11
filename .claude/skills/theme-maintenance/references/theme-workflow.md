# Theme Workflow

Work to the real scope of the theme change. The change path for an ordinary preset theme should stay short; widen the scope only when the catalog, the assets or the runtime contract changes.

## 1. Determine the change type

Answer three questions first:

1. Is this editing an existing release preset, adding a new release preset, or changing runtime theme management?
2. Does the new theme only use existing color tokens and existing illustration sets?
3. Do tokens, surfaces, the illustration asset format or the public API need to change?

Editing/adding a release preset is a release data change. Opening up runtime custom themes is a product behavior change, because the current backend's `create`, `import_themes`, `update`, `delete` and upload routes all return `theme_readonly`; do not enable it in an ordinary color request.

## 2. Read the baseline and choose the smallest change surface

First read the current `bot/web/theme_presets.json`, the relevant tokens and the relevant illustration scenes. Copy the existing theme object closest to the target, keep the complete `appearance` structure, then modify the colors, typography or illustration references item by item. Do not assemble a theme from an empty object, and do not delete a token just because no component uses it for the moment.

The minimal files for an ordinary theme change are usually:

- `bot/web/theme_presets.json`
- the backend/frontend tests affected by the manifest identity
- the paragraphs in `README.md` and `README.en.md` that list theme names or the read-only behavior

As long as an existing illustration set is used, do not change `theme_illustrations.json`, the static assets, the backend set ID constants or the frontend illustration registries.

## 3. Edit an existing release preset

When editing an existing theme:

1. Keep the theme `id` unchanged, and keep `baseId: "paper-daylight"`, `schemaVersion: 1` and `readonly: true` unchanged.
2. Change only the `appearance` fields that need to change; `colors.overrides` uses real token keys from the catalog.
3. Prefer eight-digit uppercase hex for colors; opaque tokens use `FF` alpha. For a value that the catalog's `derive` can produce, write an override only when the theme really needs a different result.
4. Copy the metadata of illustration layers directly from the catalog; do not hand-write an asset description whose hash or dimensions disagree with the catalog.
5. When the content changes, increment `version` and update `updatedAt` with a UTC ISO time; do not change the ID to avoid a version change.
6. Keep the theme list order deliberate and stable, with the default `paper-daylight` still first.

## 4. Add a new release preset

If the new theme only uses existing tokens and illustration sets:

1. Copy a complete object from an existing theme.
2. Generate a stable, unused ID of `theme_` plus 32 lowercase hex digits.
3. Set the new name, color scheme, color overrides, typography and the illustration scenes of the three surfaces.
4. Keep `readonly: true`, and place the theme at an explicit position in the `themes` array.
5. Do not append login-page theme constants to `front/src/theme.ts`; the login page reads the release manifest through the public theme API, and the default fallback is still provided by `paper-daylight`.
6. Update every stable assertion and README text that hard-codes preset theme names, counts or IDs.

If the new theme uses an existing illustration set, finishing this step is enough to move on to verification; do not copy a set of static images for every theme.

## 5. Add or replace built-in illustrations

Do this step only when a theme needs a new asset set or the content of existing assets changes:

1. Put the actual assets in `front/public/assets/theme-illustrations/<set-id>/<surface>/`, with path names matching the catalog. The backend currently validates that asset paths in the release catalog are `.webp`.
2. Compute the MIME type, pixel dimensions and SHA-256 of each file and write them into the corresponding layer in `bot/web/theme_illustrations.json`. The `assetId`, path, hash, dimensions and file content must correspond exactly.
3. Provide at least one layer on each of the three surfaces for the new set; layer IDs are unique within their own scene, and the layout values stay within the ranges of the theme spec.
4. Add the new ID to `_ILLUSTRATION_SET_IDS` in `bot/web/theme_store.py`; add the same ID to the union type in `front/src/theme/types.ts` and to the set ID, options and template arrays in `front/src/theme/illustrationPresets.ts`. Keep the naming consistent when updating display labels and color templates.
5. Reference the new set from `theme_presets.json`, and add a focused test for the asset paths or scene resolution.
6. When replacing existing assets, keep the asset ID rule and update the hashes, dimensions and the affected preset themes together; do not let an old theme keep declaring the old metadata.

If you are only switching an existing theme to an existing set, skip the registry and asset work in this section.

## 6. Modify the color catalog or the theme contract

Adding/removing tokens, CSS variables, surfaces or resolution rules affects every theme:

- First check the `derive` dependencies, alpha rules, contrast targets and `terminal` markers in `theme_catalog.json`.
- Then check the consumers: `resolveAppearance.ts`, `AppearanceProvider.tsx`, the theme manager, component CSS and the terminal mapping.
- If a surface or an illustration field is added, update the backend normalization, the frontend types, the resolver, the defaults, the import migration and the tests together.
- Keep compatible defaults for existing themes; if `schemaVersion` must be raised, design an explicit migration and update every reader and writer together.

A task of this kind is no longer a plain `theme_presets.json` edit and should be verified as a cross-module contract change.

## 7. Verification

Run the cheap static checks first, then the focused tests:

1. Parse `bot/web/theme_catalog.json`, `bot/web/theme_illustrations.json` and `bot/web/theme_presets.json`, and confirm that the JSON is valid, theme IDs are unique, the default theme exists, and every built-in asset ID of every theme can be found in the illustration catalog.
2. For changes that involve backend data or the read-only boundary, run:

   ```powershell
   python -m pytest tests/test_theme_store.py tests/test_theme_api.py -q
   ```

   If the storage locator committed on this machine conflicts with the temporary `TCB_DATA_DIR` of the repository test fixture, keep the locator without migrating or deleting it; for these two theme tests, which do not depend on the shared fixture, `python -m pytest --noconftest tests/test_theme_store.py tests/test_theme_api.py -q` can be used as a limited fallback, and this must be stated in the delivery notes.

3. For changes that involve frontend resolution, the client, the manager or illustrations, run in the `front` directory:

   ```powershell
   npm exec vitest run src/test/theme.test.ts src/test/theme-client.test.ts src/test/theme-illustrations.test.tsx src/test/theme-manager.test.tsx -- --maxWorkers=1 --fileParallelism=false
   npm run lint
   npm run build
   ```

   If the command-line version does not accept the extra Vitest arguments, run `npm run test:gate` directly and report the actual command and result.

4. If the layout, the visible illustration area or asset loading changed, run the corresponding Playwright checks against the application the user has already started; the agent must not start a development service, a preview or a temporary HTTP service.
5. Finally run `git diff --check`, check that the JSON diff does not accidentally delete tokens, themes or asset references, and confirm whether generated output such as `front/dist` belongs to the current repository conventions.

Theme copy or mechanical JSON adjustments do not need new tests. New theme identities, illustration paths, asset integrity, the read-only boundary and resolution behavior are stable contracts; update or keep the test at the most appropriate layer, and avoid duplicating assertions across the component, page and shell layers.

## 8. Delivery notes

On delivery, describe the changes to the currently effective theme manifest, the source files modified, and the test/build commands actually run with their results. If no browser check was run, point out that the layout or asset-loading boundary is still uncovered; do not describe unfinished runtime theme CRUD as supported.
