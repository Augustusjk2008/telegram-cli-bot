import io
import json
import urllib.error

import pytest

from bot.cluster.mcp_client import McpBridgeConfig, post_mcp_tool


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _http_error(url: str, status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, status, "Bad Gateway", {}, io.BytesIO(body))


def test_post_mcp_tool_retries_read_only_tools_after_transient_bad_gateway(monkeypatch) -> None:
    config = McpBridgeConfig(bridge_url="http://bridge.test", token="token")
    attempts: list[str] = []

    def fake_urlopen(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) == 1:
            raise _http_error(request.full_url, 502)
        return _Response({"ok": True, "data": {"status": "ok"}})

    monkeypatch.setattr("bot.cluster.mcp_client.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("bot.cluster.mcp_client.time.sleep", lambda _seconds: None)

    result = post_mcp_tool(config, "poll_agent_tasks", {}, run_id="clr_1")

    assert result == {"ok": True, "data": {"status": "ok"}}
    assert len(attempts) == 2


def test_post_mcp_tool_reports_context_when_bad_gateway_persists(monkeypatch) -> None:
    config = McpBridgeConfig(bridge_url="http://bridge.test", token="token")

    def fake_urlopen(request, timeout):
        raise _http_error(request.full_url, 502)

    monkeypatch.setattr("bot.cluster.mcp_client.urllib.request.urlopen", fake_urlopen)

    result = post_mcp_tool(config, "poll_agent_tasks", {}, run_id="clr_1")

    assert result["ok"] is False
    assert result["status"] == 502
    assert "HTTP 502" in str(result["error"])
    assert "poll_agent_tasks" in str(result["error"])


@pytest.mark.parametrize("tool_name", ["configure_team", "ask_agent", "cancel_agent_task", "new_agent_session", "update_agent_tier"])
def test_post_mcp_tool_does_not_retry_side_effecting_tools(monkeypatch, tool_name: str) -> None:
    config = McpBridgeConfig(bridge_url="http://bridge.test", token="token")
    attempts: list[str] = []

    def fake_urlopen(request, timeout):
        attempts.append(request.full_url)
        raise _http_error(request.full_url, 502)

    monkeypatch.setattr("bot.cluster.mcp_client.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("bot.cluster.mcp_client.time.sleep", lambda _seconds: None)

    result = post_mcp_tool(config, tool_name, {}, run_id="clr_1")

    assert result["ok"] is False
    assert len(attempts) == 1


def test_tier_edit_authority_travels_only_in_the_update_header(monkeypatch) -> None:
    from bot.cluster.config import TIER_EDITOR_ENV, TIER_EDITOR_HEADER

    monkeypatch.setenv(TIER_EDITOR_ENV, "main-only")
    headers = []
    def inspect_request(request, timeout):
        headers.append(dict((k.lower(), v) for k, v in request.header_items()))
        assert b"main-only" not in request.data
        return _Response({"ok": True})
    monkeypatch.setattr("bot.cluster.mcp_client.urllib.request.urlopen", inspect_request)
    for name in ["update_agent_tier", "get_agent_tiers"]:
        post_mcp_tool(McpBridgeConfig("http://bridge.test", "bridge"), name, {}, run_id="test-run")
    assert headers[0][TIER_EDITOR_HEADER.lower()] == "main-only"
    assert TIER_EDITOR_HEADER.lower() not in headers[1]
