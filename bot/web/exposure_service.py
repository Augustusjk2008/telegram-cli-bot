"""Public exposure snapshot aggregation."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ExposureMode = Literal["disabled", "cloudflare_quick", "fixed_public_forward", "manual"]


@dataclass(frozen=True)
class PublicExposureSnapshot:
    mode: ExposureMode
    status: str
    phase: str
    source: str
    public_url: str
    local_url: str
    last_error: str = ""
    verified: bool = False
    last_probe_at: str = ""
    last_probe_elapsed_ms: int = 0
    last_probe_error: dict[str, Any] = field(default_factory=dict)
    registered_at: str = ""
    log_tail: list[str] = field(default_factory=list)
    pid: int | None = None
    fixed_public_forward_enabled: bool = False
    node_id: str = ""
    base_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WebExposureService:
    """Combines fixed public forward config with Cloudflare tunnel state."""

    def __init__(
        self,
        *,
        tunnel_service: Any,
        fixed_public_forward_enabled: bool = False,
        fixed_public_forward_url: str = "",
        hub_node_token: str = "",
        node_id: str = "",
        base_path: str = "",
    ) -> None:
        self._tunnel_service = tunnel_service
        self._fixed_public_forward_enabled = bool(fixed_public_forward_enabled)
        self._fixed_public_forward_url = fixed_public_forward_url.strip()
        self._hub_node_token = hub_node_token.strip()
        self._node_id = node_id.strip()
        self._base_path = base_path.strip().rstrip("/")

    def snapshot(self) -> dict[str, Any]:
        tunnel_snapshot = self._tunnel_snapshot()
        if self._fixed_public_forward_enabled:
            last_error = ""
            verified = True
            if not self._fixed_public_forward_url:
                last_error = "固定公网入口 URL 未配置"
                verified = False
            elif not self._hub_node_token:
                last_error = "Hub 节点授权码未配置"
                verified = False
            status = "running" if verified else "error"
            return PublicExposureSnapshot(
                mode="fixed_public_forward",
                status=status,
                phase=status,
                source="fixed_public_forward",
                public_url=self._fixed_public_forward_url,
                local_url=str(tunnel_snapshot.get("local_url") or ""),
                last_error=last_error,
                verified=verified,
                fixed_public_forward_enabled=True,
                node_id=self._node_id,
                base_path=self._base_path,
            ).to_dict()

        return {
            **tunnel_snapshot,
            "fixed_public_forward_enabled": False,
            "node_id": self._node_id,
            "base_path": self._base_path,
        }

    def is_fixed_public_forward(self) -> bool:
        return self._fixed_public_forward_enabled

    def public_url(self) -> str:
        return str(self.snapshot().get("public_url") or "").strip().rstrip("/")

    def _tunnel_snapshot(self) -> dict[str, Any]:
        snapshot = self._tunnel_service.snapshot()
        return copy.deepcopy(snapshot if isinstance(snapshot, dict) else {})
