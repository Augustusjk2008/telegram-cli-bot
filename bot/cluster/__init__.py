"""Agent cluster package."""

from typing import Any


class ClusterToolError(RuntimeError):
    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})
        self.current_run_id = str(self.data.get("run_id") or "").strip()
