# Plugin System

## Modules and data

- Plugins live under `get_tcb_home_root()/plugins`, by default `~/.tcb/plugins`, and follow the locator after storage migration. Overriding only the app data directory with `TCB_DATA_DIR` does not change the plugin root.
- Manifest: `bot/plugins/manifest.py`, `models.py`; registry/file matching: `registry.py`; process and Host API: `runtime.py`, `host_api.py`; orchestration, view sessions, cache, artifacts and audit: `service.py`, `view_sessions.py`, `artifacts.py`, `audit.py`; allowlist-constrained external runtime installation: `runtime_installers.py`.
- Web route registration: `bot/web/routes/plugin_routes.py`; permissions and input validation: `bot/web/plugin_api_service.py`; server handler: `bot/web/server.py`.
- Bundled plugins come from `examples/plugins/`; for installation and sync see `installer.py` and `catalog.py`. Temporary artifacts and audit currently live in `repo_root/.plugins/artifacts` and `repo_root/.plugins/audit` respectively; storage migration excludes that repository directory.

## Installation and refresh

- The CLI `python -m bot.plugins.installer --repo-root <repo> --all`, or repeated `--plugin <id>`, installs the example plugins; installed ones are skipped by default, and `--force` overwrites explicitly. Web install, uninstall and configuration changes require `run_plugins`, and listing requires `view_plugins`; a custom `sourcePath` additionally requires a local request, a local administrator and development mode. Directory installation discovers `plugin.json` recursively and first checks for duplicate IDs/target directory names; each plugin in the result carries `previousVersion` and an `installOutcome` derived from the version before installation (`installed`/`upgraded`/`reinstalled`/`downgraded`, compared by SemVer, with version changes that cannot be ordered recorded as `upgraded`), and after a Web installation finishes a result dialog shows the count of each category.
- On service initialization or scan, the manifest is synced only for bundled plugins that are installed and whose source file contents are identical, keeping the installed `enabled` and `config`; sync is skipped when backend files differ or are missing. Source updates must be copied to the runtime directory by reinstalling.
- Updating a plugin through the Web API merges the configuration, writes the manifest, rediscovers immediately, then clears the view sessions and stops that plugin's process; later executions start it on demand.
- Web refresh calls `reload_plugins()`, which runs invalidation cleanup only for plugins whose manifest signature changed or that were removed; pure backend source edits are not part of the manifest signature, so a refresh cannot guarantee that the process restarts. Configuration updates and overwrite installs take the explicit invalidation path.

## Behavior that must be preserved

- The current `plugin.json` only accepts schema v2; `views[].viewMode`, `views[].dataProfile`, `runtime.permissions`, `runtime.limits`, `configSchema`, `catalogActions`, `fileHandlers` and the optional `icon` all belong to the current v2 contract.
- `icon` is a relative path inside the plugin directory (`.svg`/`.png`/`.webp`); the manifest is rejected when the path escapes the directory or the type does not match, and the icon is ignored when the file is missing, larger than 128 KiB or escapes through a symlink. The list payload returns `iconUrl` as a data URL, and the frontend `PluginIcon` generates an icon from the extension/renderer when it is absent.
- The runtime currently only supports `type=python` and `protocol=jsonrpc-stdio`, uses the host Python, reuses processes by `(bot_alias, plugin_id)`, and uses the plugin directory as cwd. The Host API permissions/limits constrain the host interfaces; the plugin process still inherits the host environment and operating system permissions.
- The Host API must gate workspace reads, directory listing, controlled workspace writes and artifact writes by the manifest permissions and limits; workspace paths must stay inside the root, workspace files are written atomically under the per-file size limit, and artifacts are stored under per-item, count and total-size quotas.
- External plugin runtimes are limited to the fixed downloads in the allowlist, currently Windows x64 Graphviz `16.1.0` for `mermaid-visio/graphviz`. The download uses HTTPS, verifies SHA-256, limits the archive size, rejects escaping paths, symlinks, device names and unsafe file types, and completes the installation with a recoverable directory replacement; a plugin must not bring its own installation parameters such as the download URL/checksum.
- The plugin service's invalidation path clears view sessions, artifacts, the snapshot cache and the associated in-flight state and stops the plugin process; runtime and Host API events are written to the audit. The snapshot cache has LRU limits on both entries and bytes.
- The Vivado backend uses Python JSON-RPC stdio, builds the VCD index by source fingerprint, and returns the visible time/signal window on demand.
- `config.lodEnabled` controls dense-segment LOD; compression must not hide signal activity.

## Verification

- Plugin runtime and Host API: `tests/test_plugin_runtime.py`, `tests/test_plugins_host_api.py`.
- External runtime installers: `tests/test_plugin_runtime_installers.py`.
- Directory installation outcome classification: `tests/test_plugin_install_outcomes.py`.
- When the plugin file view or waveform UI is involved, run `npm run test:gate`, `npm run lint` and `npm run build`, and complete interactive acceptance in a manually started application.
