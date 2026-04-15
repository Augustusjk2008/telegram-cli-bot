from __future__ import annotations

from dataclasses import dataclass
import errno
import socket


_MAX_TCP_PORT = 65535


@dataclass(frozen=True)
class RuntimeWebBind:
    host: str
    configured_port: int
    actual_port: int

    @property
    def port_changed(self) -> bool:
        return self.actual_port != self.configured_port


def _normalize_host(host: str) -> str:
    normalized = str(host or "").strip() or "0.0.0.0"
    if normalized.startswith("[") and normalized.endswith("]"):
        return normalized[1:-1]
    return normalized


def _validate_port(port: int) -> int:
    value = int(port)
    if not 1 <= value <= _MAX_TCP_PORT:
        raise ValueError(f"WEB_PORT must be between 1 and {_MAX_TCP_PORT}: {value}")
    return value


def _is_port_in_use_error(exc: OSError) -> bool:
    if exc.errno == errno.EADDRINUSE:
        return True
    return getattr(exc, "winerror", None) == 10048


def _build_sockaddr(host: str, port: int) -> tuple[int, tuple[object, ...]]:
    normalized_host = _normalize_host(host)
    if ":" in normalized_host:
        return socket.AF_INET6, (normalized_host, port, 0, 0)
    return socket.AF_INET, (normalized_host, port)


def _can_bind_host_port(host: str, port: int) -> bool:
    family, sockaddr = _build_sockaddr(host, port)
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.bind(sockaddr)
        sock.listen(1)
        return True
    except OSError as exc:
        if _is_port_in_use_error(exc):
            return False
        raise
    finally:
        sock.close()


def _iter_probe_hosts(host: str) -> tuple[str, ...]:
    normalized_host = _normalize_host(host)
    if normalized_host in {"0.0.0.0", "127.0.0.1"}:
        return ("0.0.0.0", "127.0.0.1")
    return (normalized_host,)


def resolve_runtime_web_bind(host: str, port: int) -> RuntimeWebBind:
    normalized_host = _normalize_host(host)
    configured_port = _validate_port(port)
    candidate_port = configured_port

    while candidate_port <= _MAX_TCP_PORT:
        if all(_can_bind_host_port(probe_host, candidate_port) for probe_host in _iter_probe_hosts(normalized_host)):
            return RuntimeWebBind(
                host=normalized_host,
                configured_port=configured_port,
                actual_port=candidate_port,
            )
        candidate_port += 1

    raise OSError(f"No available TCP port from {configured_port} to {_MAX_TCP_PORT} for host {normalized_host}")
