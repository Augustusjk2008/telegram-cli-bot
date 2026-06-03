from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from bot.web.fixed_forward_service import FixedForwardService


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return b'{"ok": true}'


class _FakeStdout:
    def __init__(self, owner, lines: list[str]):
        self._owner = owner
        self._lines = list(lines)

    def readline(self) -> str:
        if self._lines:
            return self._lines.pop(0)
        self._owner.returncode = 0
        return ""


class _FakeProcess:
    def __init__(self, lines: list[str] | None = None):
        self.pid = 4321
        self.returncode = None
        self.stdout = _FakeStdout(self, lines or [])
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9


def _service(tmp_path: Path, **overrides) -> FixedForwardService:
    kwargs = {
        "host": "0.0.0.0",
        "port": 8765,
        "enabled": True,
        "public_url": "http://124.221.226.63:18088/node/nanjing-laptop/",
        "node_id": "nanjing-laptop",
        "base_path": "/node/nanjing-laptop",
        "frps_port": 7000,
        "node_token": "node-secret",
        "frps_token": "frps-secret",
        "frpc_path": "frpc",
        "runtime_dir": tmp_path,
        "heartbeat_interval": 999,
        "startup_timeout": 0.1,
    }
    kwargs.update(overrides)
    return FixedForwardService(**kwargs)


def test_build_frpc_config_matches_hub_template(tmp_path: Path) -> None:
    service = _service(tmp_path)

    path = service.write_frpc_config()
    content = path.read_text(encoding="utf-8")

    assert path == tmp_path / "frpc.toml"
    assert 'serverAddr = "124.221.226.63"' in content
    assert "serverPort = 7000" in content
    assert 'auth.method = "token"' in content
    assert 'auth.token = "frps-secret"' in content
    assert "transport.tls.enable = true" in content
    assert 'name = "nanjing-laptop"' in content
    assert 'type = "http"' in content
    assert 'localIP = "127.0.0.1"' in content
    assert "localPort = 8765" in content
    assert 'customDomains = ["124.221.226.63"]' in content
    assert 'locations = ["/node/nanjing-laptop"]' in content
    assert 'X-Forwarded-Prefix = "/node/nanjing-laptop"' in content
    assert 'X-TCB-Node-ID = "nanjing-laptop"' in content


def test_heartbeat_posts_expected_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        return _FakeResponse()

    monkeypatch.setattr("bot.web.fixed_forward_service.urlopen", fake_urlopen)
    service = _service(tmp_path)

    result = service.send_heartbeat_once()

    assert result["ok"] is True
    assert captured["url"] == "http://124.221.226.63:18088/api/nodes/heartbeat"
    assert captured["body"]["node_id"] == "nanjing-laptop"
    assert captured["body"]["token"] == "node-secret"
    assert captured["body"]["local_url"] == "http://127.0.0.1:8765"
    assert captured["headers"]["Content-type"] == "application/json"
    snapshot = service.snapshot()
    assert snapshot["heartbeat_status"] == "online"
    assert snapshot["heartbeat_last_at"]
    assert snapshot["heartbeat_last_error"] == ""


def test_heartbeat_403_reports_node_token_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request, timeout=0):
        raise HTTPError("http://hub/api/nodes/heartbeat", 403, "Forbidden", {}, None)

    monkeypatch.setattr("bot.web.fixed_forward_service.urlopen", fake_urlopen)
    service = _service(tmp_path)

    result = service.send_heartbeat_once()

    assert result["ok"] is False
    assert result["error_class"] == "node_token"
    assert result["error_text"] == "节点 token 错"
    assert service.snapshot()["heartbeat"]["error_text"] == "节点 token 错"
    assert service.snapshot()["heartbeat_status"] == "error"
    assert service.snapshot()["heartbeat_last_error"] == "节点 token 错"


def test_frps_timeout_reports_port_not_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create_connection(_address, timeout=0):
        raise TimeoutError("timed out")

    monkeypatch.setattr("bot.web.fixed_forward_service.socket.create_connection", fake_create_connection)
    service = _service(tmp_path)

    result = service.check_frps_connectivity()

    assert result["ok"] is False
    assert result["error_class"] == "frps_timeout"
    assert result["error_text"] == "frps 端口不通/安全组未放通"


@pytest.mark.asyncio
async def test_frpc_auth_failure_is_mapped_to_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(["login to server failed: authorization failed\n"])

    monkeypatch.setattr("bot.web.fixed_forward_service.subprocess.Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        "bot.web.fixed_forward_service.FixedForwardService.check_frps_connectivity",
        lambda self: {"ok": True, "error_class": "", "error_text": ""},
    )
    service = _service(tmp_path, startup_timeout=0.5)

    snapshot = await service.start()

    assert snapshot["status"] == "error"
    assert snapshot["last_error"] == "frps token 错"
    assert snapshot["frpc_status"] == "error"
    assert snapshot["frpc_last_error"] == "frps token 错"
    assert "authorization failed" in snapshot["log_tail"][0]
