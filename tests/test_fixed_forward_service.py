import io
from pathlib import Path

import pytest

from bot.web.fixed_forward_service import FixedForwardService


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
