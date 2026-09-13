import io
import ssl
from pathlib import Path

import pytest

from bot.web.fixed_forward_service import FixedForwardService, _frpc_spawn_env


class DummyProcess:
    pid = 4321

    def __init__(self, output: str = "") -> None:
        self.stdout = io.StringIO(output)
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode


def _service(tmp_path: Path, *, instance_id: str = "current-instance") -> FixedForwardService:
    return FixedForwardService(
        host="127.0.0.1",
        port=8768,
        enabled=True,
        public_url="https://hub.example.test/node/node-a",
        node_id="node-a",
        base_path="/node/node-a",
        frps_port=7000,
        node_token="node-token",
        frps_token="frps-token",
        runtime_dir=tmp_path,
        startup_timeout=0.01,
        instance_id=instance_id,
    )


@pytest.mark.asyncio
async def test_start_reuses_external_frpc_when_public_health_matches_current_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    popen_calls: list[object] = []

    monkeypatch.setattr(service, "check_frps_connectivity", lambda: {"ok": True})
    monkeypatch.setattr(
        service,
        "_fetch_public_health",
        lambda: {"ok": True, "instance_id": "current-instance", "node_id": "node-a", "base_path": "/node/node-a"},
    )
    monkeypatch.setattr("bot.web.fixed_forward_service.subprocess.Popen", lambda *args, **kwargs: popen_calls.append(args) or DummyProcess())

    snapshot = await service.start()

    assert popen_calls == []
    assert snapshot["status"] == "running"
    assert snapshot["verified"] is True
    assert snapshot["pid"] is None
    assert snapshot["frpc_external"] is True
    assert snapshot["frpc_managed"] is False
    assert snapshot["frpc_note"]
    assert snapshot["last_error"] == ""
    assert snapshot["frpc_last_error"] == ""


@pytest.mark.asyncio
async def test_proxy_exists_keeps_error_when_public_health_points_to_other_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    process = DummyProcess("login to server success\nproxy [node-a] already exists\n")

    monkeypatch.setattr(service, "check_frps_connectivity", lambda: {"ok": True})
    monkeypatch.setattr(
        service,
        "_fetch_public_health",
        lambda: {"ok": True, "instance_id": "other-instance", "node_id": "node-a", "base_path": "/node/node-a"},
    )
    monkeypatch.setattr("bot.web.fixed_forward_service.subprocess.Popen", lambda *args, **kwargs: process)

    terminated: list[DummyProcess] = []

    def fake_terminate(target: DummyProcess) -> None:
        target.terminated = True
        target.returncode = 1
        terminated.append(target)

    monkeypatch.setattr("bot.web.fixed_forward_service.terminate_process_tree_sync", fake_terminate)

    snapshot = await service.start()

    assert snapshot["status"] == "error"
    assert "frps 已存在同名 proxy" in snapshot["last_error"]
    assert snapshot["verified"] is False
    assert snapshot["frpc_external"] is False
    assert snapshot["frpc_managed"] is False
    assert terminated == [process]


@pytest.mark.asyncio
async def test_proxy_exists_reuses_external_frpc_when_public_health_matches_after_frpc_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    process = DummyProcess("proxy [node-a] already exists\n")

    monkeypatch.setattr(service, "check_frps_connectivity", lambda: {"ok": True})
    health_results = [
        {"ok": False, "error_text": "not ready"},
        {"ok": True, "instance_id": "current-instance", "node_id": "node-a", "base_path": "/node/node-a"},
    ]
    monkeypatch.setattr(service, "_fetch_public_health", lambda: health_results.pop(0))
    monkeypatch.setattr("bot.web.fixed_forward_service.subprocess.Popen", lambda *args, **kwargs: process)

    terminated: list[DummyProcess] = []

    def fake_terminate(target: DummyProcess) -> None:
        target.terminated = True
        target.returncode = 1
        terminated.append(target)

    monkeypatch.setattr("bot.web.fixed_forward_service.terminate_process_tree_sync", fake_terminate)

    snapshot = await service.start()

    assert snapshot["status"] == "running"
    assert snapshot["verified"] is True
    assert snapshot["pid"] is None
    assert snapshot["frpc_external"] is True
    assert snapshot["frpc_managed"] is False
    assert snapshot["last_error"] == ""
    assert snapshot["frpc_note"]
    assert terminated == [process]


def test_frpc_spawn_env_strips_proxy_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:8086")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8086")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:8086")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.setenv("PATH_KEEP", "/usr/bin")

    env = _frpc_spawn_env()

    assert "http_proxy" not in env
    assert "HTTPS_PROXY" not in env
    assert "ALL_PROXY" not in env
    assert "no_proxy" not in env
    assert env["PATH_KEEP"] == "/usr/bin"


@pytest.mark.asyncio
async def test_start_spawns_frpc_with_proxy_free_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    popen_kwargs: dict[str, object] = {}

    monkeypatch.setenv("http_proxy", "http://127.0.0.1:8086")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8086")
    monkeypatch.setattr(service, "check_frps_connectivity", lambda: {"ok": True})
    monkeypatch.setattr(service, "_fetch_public_health", lambda: {"ok": False, "error_text": "not ready"})

    def fake_popen(*args: object, **kwargs: object) -> DummyProcess:
        popen_kwargs.update(kwargs)
        return DummyProcess("login to server success\n")

    monkeypatch.setattr("bot.web.fixed_forward_service.subprocess.Popen", fake_popen)

    await service.start()

    env = popen_kwargs.get("env")
    assert isinstance(env, dict)
    assert all("proxy" not in key.lower() for key in env)


def test_frpc_config_enables_tls_and_pool(tmp_path: Path) -> None:
    config_text = _service(tmp_path)._build_frpc_config_text()

    assert "transport.tls.enable = true" in config_text
    assert "transport.poolCount = 5" in config_text


def test_direct_opener_bypasses_proxy_and_accepts_self_signed() -> None:
    from urllib.request import HTTPSHandler

    from bot.web.fixed_forward_service import _DIRECT_OPENER, _UNVERIFIED_SSL_CONTEXT

    # ProxyHandler({}) 空 proxies 时不注册任何 *_open 方法 → opener 内不得存在配置了代理的 handler
    #（Python 3.12 下它甚至不会被加进 handlers，两种形态都断言不到代理）
    assert [h for h in _DIRECT_OPENER.handlers if getattr(h, "proxies", None)] == []

    # HTTPSHandler 必须带跳过校验的 context（公网入口为自签证书）
    https_handlers = [h for h in _DIRECT_OPENER.handlers if isinstance(h, HTTPSHandler)]
    assert any(getattr(handler, "_context", None) is _UNVERIFIED_SSL_CONTEXT for handler in https_handlers)
    assert _UNVERIFIED_SSL_CONTEXT.verify_mode == ssl.CERT_NONE
    assert _UNVERIFIED_SSL_CONTEXT.check_hostname is False
