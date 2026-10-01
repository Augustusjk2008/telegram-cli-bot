# Plugin SDK template

Copy `backend/plugin_sdk.py` into a plugin's own `backend` directory and
import `PluginServer` from the local module.  The SDK uses only Python's
standard library and keeps the JSON-RPC stdio protocol used by Orbit Safe
Claw bundled plugins.

`backend/main.py` is a minimal runnable example.  A plugin can use
`server.read_bytes(...)` and `server.write_artifact(...)` for host API calls;
the host call is answered through the same stdio stream.
