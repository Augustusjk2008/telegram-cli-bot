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


def _service(
    tmp_path: Path,
    *,
    instance_id: str = "current-instance",
    public_url: str = "https://hub.example.test/node/node-a",
    reconnect_attempts: int = 3,
    reconnect_retry_delay: float = 5.0,
    reconnect_interval: float = 10 * 60.0,
) -> FixedForwardService:
    return FixedForwardService(
        host="127.0.0.1",
        port=8768,
        enabled=True,
        public_url=public_url,
        node_id="node-a",
        base_path="/node/node-a",
        frps_port=7000,
        node_token="node-token",
        frps_token="frps-token",
        runtime_dir=tmp_path,
        startup_timeout=0.01,
        instance_id=instance_id,
        reconnect_attempts=reconnect_attempts,
        reconnect_retry_delay=reconnect_retry_delay,
        reconnect_interval=reconnect_interval,
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
    await service.stop()


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
    assert snapshot["last_error"]
    assert snapshot["verified"] is False
    assert snapshot["frpc_external"] is False
    assert snapshot["frpc_managed"] is False
    assert terminated == [process]
    await service.stop()


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
    await service.stop()


@pytest.mark.asyncio
async def test_session_shutdown_log_triggers_frpc_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    process = DummyProcess("connect to server error: session shutdown\n")

    monkeypatch.setattr(service, "check_frps_connectivity", lambda: {"ok": True})
    monkeypatch.setattr("bot.web.fixed_forward_service.subprocess.Popen", lambda *args, **kwargs: process)

    terminated: list[DummyProcess] = []

    def fake_terminate(target: DummyProcess) -> None:
        target.terminated = True
        target.returncode = 1
        terminated.append(target)

    monkeypatch.setattr("bot.web.fixed_forward_service.terminate_process_tree_sync", fake_terminate)

    snapshot = await service.start()

    assert snapshot["status"] == "error"
    assert snapshot["last_error"] == "frpc 与 frps 的连接已中断"
    assert terminated == [process]
    await service.stop()


def test_validate_config_allows_outer_reverse_proxy_prefix(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        public_url="https://hub.example.test/tcb-hub/node/node-a/",
    )

    assert service._validate_config() == ""


@pytest.mark.asyncio
async def test_try_reconnect_retries_until_frpc_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, reconnect_retry_delay=0.1)
    start_results = [
        {"status": "error"},
        {"status": "error"},
        {"status": "running"},
    ]
    start_calls: list[int] = []
    sleep_calls: list[float] = []

    async def fake_start() -> dict[str, object]:
        start_calls.append(1)
        return start_results.pop(0)

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(service, "start", fake_start)
    monkeypatch.setattr("bot.web.fixed_forward_service.asyncio.sleep", fake_sleep)

    assert await service._try_reconnect() is True
    assert len(start_calls) == 3
    assert sleep_calls == [0.1, 0.1]


@pytest.mark.asyncio
async def test_heartbeat_loop_waits_ten_minutes_after_reconnect_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, reconnect_retry_delay=0.1, reconnect_interval=600.0)
    service._set_snapshot(status="error")
    start_calls: list[int] = []
    sleep_calls: list[float] = []

    async def fake_start() -> dict[str, object]:
        start_calls.append(1)
        return {"status": "error"}

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if seconds == 600.0:
            raise RuntimeError("stop recovery loop test")

    monkeypatch.setattr(service, "start", fake_start)
    monkeypatch.setattr("bot.web.fixed_forward_service.asyncio.sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="stop recovery loop test"):
        await service._heartbeat_loop()

    assert len(start_calls) == 3
    assert sleep_calls == [0.1, 0.1, 600.0]
