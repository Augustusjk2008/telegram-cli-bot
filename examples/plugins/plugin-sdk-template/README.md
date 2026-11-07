# Plugin SDK template

Copy `backend/plugin_sdk.py` into a plugin's own `backend` directory and
import `PluginServer` from the local module.  The SDK uses only Python's
standard library and keeps the JSON-RPC stdio protocol used by Orbit Safe
Claw bundled plugins.

`backend/main.py` is a minimal runnable example.  A plugin can use
`server.read_bytes(...)` and `server.write_artifact(...)` for host API calls;
the host call is answered through the same stdio stream.

## Plugin icon

Add an optional `icon` to `plugin.json` that points to an image inside the
plugin directory, and ship the file with the plugin:

```json
{
  "schemaVersion": 2,
  "id": "my-plugin",
  "icon": "assets/icon.svg"
}
```

- Supported types: `.svg`, `.png`, `.webp`; at most 128 KiB.
- The path must be relative and stay inside the plugin directory (no `..`,
  absolute or drive paths); an invalid path rejects the manifest.
- A missing, oversized or escaping file is ignored, and the catalog falls back
  to a generated icon based on the plugin's file types and renderer.
- Design for a square canvas (e.g. `viewBox="0 0 64 64"`) with transparent
  padding; the catalog shows it at 32 px on a 44 px tile and also at 20 px.
- The host inlines the file as a data URL in the plugin list (`iconUrl`), so
  SVG is rendered as an image and cannot run scripts.
