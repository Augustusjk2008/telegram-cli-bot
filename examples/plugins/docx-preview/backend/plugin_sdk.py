"""Small standard-library helpers for JSON-RPC stdio plugins.

Copy this module into a plugin's backend directory.  It intentionally has no
dependency on the Orbit host package or on the repository root.
"""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable
from typing import Any


JsonHandler = Callable[[dict[str, Any]], dict[str, Any]]


class PluginServer:
    """Run the small JSON-RPC surface shared by simple bundled plugins."""

    def __init__(self, name: str, *, defaults: dict[str, Any] | None = None) -> None:
        self.name = name
        self._defaults = dict(defaults or {})
        self.config: dict[str, Any] = dict(self._defaults)
        self.context: dict[str, Any] = {}
        self._next_request_id = 9000
        self._handlers: dict[str, JsonHandler] = {}

    def register_handler(self, method: str, handler: JsonHandler) -> None:
        self._handlers[str(method)] = handler

    def emit(self, message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def respond(
        self,
        request_id: Any,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error:
            payload["error"] = {"code": -32000, "message": error}
        else:
            payload["result"] = result or {}
        self.emit(payload)

    def host_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self.emit({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            line = sys.stdin.readline()
            if not line:
                raise SystemExit(0)
            message = json.loads(line)
            if message.get("method"):
                continue
            if int(message.get("id") or 0) == request_id:
                return message

    # Keep the older helper spelling available to copied plugins.
    def call_host(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.host_call(method, params)

    def read_bytes(self, path: str, *, error_message: str) -> bytes:
        response = self.host_call("host.workspace.read_bytes", {"path": path})
        if response.get("error"):
            raise RuntimeError(str(response["error"].get("message") or error_message))
        content_base64 = str((response.get("result") or {}).get("contentBase64") or "")
        return base64.b64decode(content_base64.encode("ascii"))

    def read_text(
        self,
        path: str,
        *,
        encoding: str = "utf-8",
        error_message: str = "读取文本失败",
    ) -> str:
        response = self.host_call(
            "host.workspace.read_text",
            {"path": path, "encoding": encoding},
        )
        if response.get("error"):
            raise RuntimeError(str(response["error"].get("message") or error_message))
        return str((response.get("result") or {}).get("content") or "")

    def write_artifact(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        *,
        error_message: str,
    ) -> dict[str, Any]:
        response = self.host_call(
            "host.temp.write_artifact",
            {
                "filename": filename,
                "contentBase64": base64.b64encode(content).decode("ascii"),
                "contentType": content_type,
            },
        )
        if response.get("error"):
            raise RuntimeError(str(response["error"].get("message") or error_message))
        return dict(response.get("result") or {})

    def run(
        self,
        render_view: JsonHandler | None = None,
        *,
        open_view: JsonHandler | None = None,
        initialize: Callable[[dict[str, Any]], None] | None = None,
        shutdown: Callable[[], None] | None = None,
    ) -> None:
        if render_view is not None:
            self.register_handler("plugin.render_view", lambda params: render_view(dict(params.get("input") or {})))
        if open_view is None:
            open_handler = render_view
        else:
            open_handler = open_view
        if open_handler is not None:
            self.register_handler("plugin.open_view", lambda params: open_handler(dict(params.get("input") or {})))
        shutdown_called = False

        def run_shutdown() -> None:
            nonlocal shutdown_called
            if shutdown is not None and not shutdown_called:
                shutdown_called = True
                shutdown()

        try:
            for raw_line in sys.stdin:
                request = json.loads(raw_line)
                request_id = request.get("id")
                method = request.get("method")
                params = request.get("params") or {}
                try:
                    if method == "plugin.initialize":
                        context = params.get("context") or {}
                        self.context = dict(context)
                        self.config.clear()
                        self.config.update(self._defaults)
                        plugin = self.context.get("plugin") or {}
                        config = plugin.get("config") or {}
                        if isinstance(config, dict):
                            self.config.update(config)
                        if initialize is not None:
                            initialize(self.context)
                        self.respond(request_id, {"ok": True, "name": self.name})
                    elif method == "plugin.shutdown":
                        run_shutdown()
                        self.respond(request_id, {"ok": True})
                    else:
                        handler = self._handlers.get(str(method))
                        if handler is None:
                            self.respond(request_id, error=f"unsupported method: {method}")
                        else:
                            self.respond(request_id, handler(dict(params)))
                except Exception as exc:  # pragma: no cover - surfaced through the protocol
                    self.respond(request_id, error=str(exc))
        finally:
            run_shutdown()
