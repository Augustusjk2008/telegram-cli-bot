---
name: theme-maintenance
description: "Add, edit, validate and release frontend themes in Orbit Safe Claw, covering color tokens, preset themes, the illustration catalog and its assets."
metadata:
  short-description: "Maintain Orbit Safe Claw theme colors, the illustration catalog and the release workflow"
---

# Theme Maintenance

Use this for Orbit Safe Claw theme presets, color tokens, illustration assets and pre-release theme verification. First decide whether the request is editing an existing preset, adding a new release preset, adding illustration assets, or changing the theme runtime capability, then follow the matching flow.

Read [theme-spec.md](references/theme-spec.md) first to understand the current data contract and runtime boundaries; when actual changes are needed, read [theme-workflow.md](references/theme-workflow.md) and follow the workflow. Read only the reference content relevant to the current task.

## Working principles

- Treat `bot/web/theme_presets.json`, `bot/web/theme_catalog.json` and `bot/web/theme_illustrations.json` as the source files of the released theme data. The frontend parser and the backend validator jointly constrain their format.
- Distinguish "release preset themes" from "runtime theme management" first. The eight currently released themes are all read-only presets; the runtime only persists each account's selected theme, and the endpoints for creating, updating, deleting and importing themes and uploading assets reject requests. Adding a release preset does not call for enabling runtime CRUD along the way.
- When modifying an existing theme, keep the existing ID, `baseId`, `schemaVersion`, read-only attribute and illustration asset metadata stable; when the content changes, increment the theme `version` and update the timezone-aware `updatedAt`.
- Colors only reference token keys in the current catalog. Check opacity, derived colors, contrast, terminal colors and illustration layers against the reference spec, rather than looking only at the login page or a single preview area.
- When adding an illustration set, update the asset files, the illustration catalog, the set IDs allowed by the backend, and the frontend types and options together; when only adding a theme that uses an existing illustration set, do not change these registries.
- When the theme manifest or a stable field changes, update the corresponding backend/frontend contract assertions and the Chinese and English READMEs; ordinary copy or mechanical JSON changes do not get new duplicate tests.
- After the change, run at least the backend theme tests, the frontend theme tests, the TypeScript check and the production build. Do not start a development server or a temporary preview server.

## Quick routing

- Only changing colors, typography or an existing illustration combination: read the "Theme object" and color/illustration sections of the theme spec, then follow the release preset flow.
- Adding a new release theme: mainly modify `theme_presets.json`, and update the manifest assertions and documentation together.
- Adding or replacing a set of built-in illustrations: read the illustration catalog constraints in the theme spec and the asset steps in the workflow; the hard-coded set ID registries need to change.
- Modifying tokens, surfaces, CSS variables or theme runtime behavior: treat it as a theme contract change, check all consumers and tests first, then widen the verification scope.
- The user asks to open up custom themes, import, deletion or upload: stop and treat it as a separate design scope, explain that the current backend intentionally returns a read-only error, and do not handle it as an ordinary preset theme edit.
