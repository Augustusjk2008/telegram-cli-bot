from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from bot.native_agent import pi_rpc_client
from bot.native_agent.pi_rpc_client import PiRpcClient, PiRpcRunError, PiRpcStartRequest


FAKE_PI = r"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

mode = os.environ.get("FAKE_PI_MODE", "events")
input_log = os.environ.get("FAKE_PI_INPUT_LOG", "")
ready_log = os.environ.get("FAKE_PI_READY_LOG", "")


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def record(line):
    if input_log:
        with Path(input_log).open("a", encoding="utf-8") as handle:
            handle.write(line)


def mark_ready():
    if ready_log:
        Path(ready_log).write_text("ready", encoding="utf-8")


if mode == "events":
    emit({"type": "ready", "cwd": os.getcwd()})
    emit({"type": "done"})
    raise SystemExit(0)

if mode == "invalid":
    emit({"type": "ready"})
    print("not-json", flush=True)
    emit({"type": "done"})
    raise SystemExit(0)

if mode == "stderr_exit":
    emit({"type": "before-exit"})
    for index in range(260):
        sys.stderr.write(f"err-{index:03d} " + ("x" * 900) + "\n")
    sys.stderr.flush()
    raise SystemExit(7)

if mode == "wait_input":
    for line in sys.stdin:
        record(line)
        packet = json.loads(line)
        if packet.get("type") == "abort":
            raise SystemExit(0)
        emit({"type": "received", "packet": packet})
    raise SystemExit(0)

if mode == "state_response":
    for line in sys.stdin:
        record(line)
        packet = json.loads(line)
        if packet.get("type") == "get_state":
            emit({"type": "startup_event"})
            emit({
                "id": packet.get("id"),
                "type": "response",
                "command": "get_state",
                "success": True,
                "data": {
                    "sessionId": "pi-sess-1",
                    "sessionFile": "session.jsonl",
                    "messageCount": 0,
                },
            })
            raise SystemExit(0)

if mode == "state_error":
    for line in sys.stdin:
        record(line)
        packet = json.loads(line)
        if packet.get("type") == "get_state":
            emit({
                "id": packet.get("id"),
                "type": "response",
                "command": "get_state",
                "success": False,
                "error": "state failed",
            })
            raise SystemExit(0)

if mode == "ignore_abort":
    mark_ready()
    for line in sys.stdin:
        record(line)
        json.loads(line)
    time.sleep(60)

if mode == "half_line":
    sys.stdout.write('{"type":"partial"')
    sys.stdout.flush()
    time.sleep(0.35)
    sys.stdout.write('}\n')
    sys.stdout.flush()
    raise SystemExit(0)

if mode == "close_wait":
    sys.stdin.read()
    raise SystemExit(0)

if mode == "hang_on_close":
    sys.stdin.read()
    time.sleep(60)
"""


def _write_fake_pi(tmp_path: Path) -> Path:
    script = tmp_path / "fake_pi.py"
    script.write_text(FAKE_PI, encoding="utf-8")
    return script


async def _start_fake_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    *,
    timeout_seconds: float | None = 1.0,
    input_log: Path | None = None,
    ready_log: Path | None = None,
) -> PiRpcClient:
    script = _write_fake_pi(tmp_path)
    monkeypatch.setattr(pi_rpc_client, "resolve_cli_executable", lambda _command, _cwd=None: "fake-pi")
    monkeypatch.setattr(pi_rpc_client, "build_executable_invocation", lambda _resolved: [sys.executable, str(script)])
    env = {"FAKE_PI_MODE": mode}
    if input_log is not None:
        env["FAKE_PI_INPUT_LOG"] = str(input_log)
    if ready_log is not None:
        env["FAKE_PI_READY_LOG"] = str(ready_log)
    return await PiRpcClient.start(PiRpcStartRequest(command="pi", cwd=tmp_path / ".", env=env, timeout_seconds=timeout_seconds))


async def _wait_for_file(path: Path) -> None:
    for _ in range(40):
        if path.exists():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{path} was not created")


async def _collect(client: PiRpcClient) -> list[dict[str, Any]]:
    return await asyncio.wait_for(_collect_unbounded(client), timeout=3)


async def _collect_unbounded(client: PiRpcClient) -> list[dict[str, Any]]:
    return [event async for event in client.events()]


@pytest.mark.asyncio
async def test_pi_rpc_client_streams_jsonl_events_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "events")

    events = await _collect(client)

    assert events == [
        {"type": "ready", "cwd": str(tmp_path.resolve())},
        {"type": "done"},
    ]


@pytest.mark.asyncio
async def test_pi_rpc_client_converts_invalid_json_to_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "invalid")

    events = await _collect(client)

    assert events[0] == {"type": "ready"}
    assert events[1]["type"] == "diagnostic"
    assert events[1]["source"] == "pi_rpc_transport"
    assert events[1]["level"] == "warning"
    assert "not-json" in events[1]["raw"]
    assert events[2] == {"type": "done"}


@pytest.mark.asyncio
async def test_pi_rpc_client_stderr_drain_and_nonzero_error_include_tails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "stderr_exit")

    with pytest.raises(PiRpcRunError) as exc_info:
        await _collect(client)

    assert exc_info.value.returncode == 7
    assert "err-259" in exc_info.value.stderr
    assert "before-exit" in exc_info.value.stdout
    assert "Pi RPC 退出码 7" in str(exc_info.value)
    assert len(str(exc_info.value)) < 2500


@pytest.mark.asyncio
async def test_pi_rpc_client_send_writes_single_jsonl_packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_log = tmp_path / "stdin.log"
    client = await _start_fake_client(tmp_path, monkeypatch, "wait_input", input_log=input_log)
    stream = client.events().__aiter__()

    await client.send({"type": "custom", "value": 1})
    event = await asyncio.wait_for(stream.__anext__(), timeout=2)
    await client.close()

    assert event == {"type": "received", "packet": {"type": "custom", "value": 1}}
    assert input_log.read_text(encoding="utf-8").splitlines() == ['{"type":"custom","value":1}']


@pytest.mark.asyncio
async def test_pi_rpc_client_send_after_immediate_exit_reports_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "stderr_exit")
    await asyncio.sleep(0.2)

    with pytest.raises(PiRpcRunError) as exc_info:
        await client.send({"type": "custom"})

    assert exc_info.value.returncode == 7
    assert "err-259" in exc_info.value.stderr
    assert "Pi RPC 退出码 7" in str(exc_info.value)


@pytest.mark.asyncio
async def test_pi_rpc_client_prompt_adds_text_and_conversation_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "wait_input")
    stream = client.events().__aiter__()

    await client.prompt("你好", conversation_id="conv-1", agent_id="reviewer", reasoning_effort="high")
    first = await asyncio.wait_for(stream.__anext__(), timeout=2)
    second = await asyncio.wait_for(stream.__anext__(), timeout=2)
    await client.close()

    assert first == {
        "type": "received",
        "packet": {"type": "set_thinking_level", "level": "high"},
    }
    assert second == {
        "type": "received",
        "packet": {
            "type": "prompt",
            "message": "/reviewer 你好",
            "conversation_id": "conv-1",
        },
    }


@pytest.mark.asyncio
async def test_pi_rpc_client_get_state_reads_response_before_event_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "state_response")

    state = await client.get_state()
    events = await _collect(client)

    assert state["sessionId"] == "pi-sess-1"
    assert state["sessionFile"] == "session.jsonl"
    assert state["messageCount"] == 0
    assert events == [{"type": "startup_event"}]


@pytest.mark.asyncio
async def test_pi_rpc_client_get_state_error_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "state_error")

    with pytest.raises(PiRpcRunError, match="state failed"):
        await client.get_state()


@pytest.mark.asyncio
async def test_pi_rpc_client_waits_for_lf_before_parsing_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = await _start_fake_client(tmp_path, monkeypatch, "half_line")
    stream = client.events().__aiter__()

    pending = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.1)
    assert pending.done() is False

    assert await asyncio.wait_for(pending, timeout=2) == {"type": "partial"}


@pytest.mark.asyncio
async def test_pi_rpc_client_abort_sends_abort_packet_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_log = tmp_path / "stdin.log"
    client = await _start_fake_client(tmp_path, monkeypatch, "wait_input", input_log=input_log)

    await client.abort()
    await client.abort()

    assert json.loads(input_log.read_text(encoding="utf-8").splitlines()[0]) == {"type": "abort"}


@pytest.mark.asyncio
async def test_pi_rpc_client_abort_timeout_escalates_to_tree_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_log = tmp_path / "stdin.log"
    ready_log = tmp_path / "ready.txt"
    killed = []

    def fake_terminate_tree(process: subprocess.Popen[str]) -> None:
        killed.append(process.pid)
        process.kill()
        process.wait(timeout=2)

    monkeypatch.setattr(pi_rpc_client, "terminate_process_tree_sync", fake_terminate_tree)
    client = await _start_fake_client(
        tmp_path,
        monkeypatch,
        "ignore_abort",
        timeout_seconds=0.5,
        input_log=input_log,
        ready_log=ready_log,
    )
    await _wait_for_file(ready_log)

    await client.abort()

    assert killed
    assert json.loads(input_log.read_text(encoding="utf-8").splitlines()[0]) == {"type": "abort"}


@pytest.mark.asyncio
async def test_pi_rpc_client_close_is_idempotent_after_normal_eof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    killed = []
    monkeypatch.setattr(pi_rpc_client, "terminate_process_tree_sync", lambda process: killed.append(process.pid))
    client = await _start_fake_client(tmp_path, monkeypatch, "close_wait")

    await client.close()
    await client.close()

    assert killed == []


@pytest.mark.asyncio
async def test_pi_rpc_client_close_timeout_escalates_to_tree_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed = []

    def fake_terminate_tree(process: subprocess.Popen[str]) -> None:
        killed.append(process.pid)
        process.kill()
        process.wait(timeout=2)

    monkeypatch.setattr(pi_rpc_client, "terminate_process_tree_sync", fake_terminate_tree)
    client = await _start_fake_client(tmp_path, monkeypatch, "hang_on_close", timeout_seconds=0.1)

    await client.close()

    assert killed


@pytest.mark.asyncio
async def test_pi_rpc_client_kill_uses_process_tree_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    killed = []

    def fake_terminate_tree(process: subprocess.Popen[str]) -> None:
        killed.append(process.pid)
        process.kill()
        process.wait(timeout=2)

    monkeypatch.setattr(pi_rpc_client, "terminate_process_tree_sync", fake_terminate_tree)
    client = await _start_fake_client(tmp_path, monkeypatch, "ignore_abort")

    await client.kill()
    await client.kill()

    assert len(killed) == 1


@pytest.mark.asyncio
async def test_pi_rpc_client_start_uses_default_pi_rpc_command_and_process_kwargs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeProcess:
        pid = 4321
        stdin = None
        stdout = None
        stderr = None
        returncode = 0

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(args: list[str], **kwargs: Any) -> FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(pi_rpc_client, "resolve_cli_executable", lambda command, _cwd=None: f"C:/Program Files/Pi/{command}.cmd")
    monkeypatch.setattr(pi_rpc_client, "build_executable_invocation", lambda resolved: ["cmd.exe", "/d", "/c", resolved])
    monkeypatch.setattr(pi_rpc_client, "build_chat_cli_process_kwargs", lambda: {"creationflags": 123})
    monkeypatch.setattr(pi_rpc_client.subprocess, "Popen", fake_popen)

    await PiRpcClient.start(
        PiRpcStartRequest(
            command=None,
            cwd=tmp_path / ".",
            model="anthropic/claude-sonnet-4",
            session_id="pi-sess-1",
        )
    )

    assert captured["args"] == [
        "cmd.exe",
        "/d",
        "/c",
        "C:/Program Files/Pi/pi.cmd",
        "--mode",
        "rpc",
        "--session",
        "pi-sess-1",
        "--model",
        "anthropic/claude-sonnet-4",
    ]
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())
    assert captured["kwargs"]["creationflags"] == 123


@pytest.mark.asyncio
async def test_pi_rpc_client_start_maps_portable_pi_home_to_child_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    pi_home = tmp_path / "pi-home"

    class FakeProcess:
        pid = 4321
        stdin = None
        stdout = None
        stderr = None
        returncode = 0

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(args: list[str], **kwargs: Any) -> FakeProcess:
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(pi_rpc_client, "resolve_cli_executable", lambda command, _cwd=None: command)
    monkeypatch.setattr(pi_rpc_client, "build_executable_invocation", lambda resolved: [resolved])
    monkeypatch.setattr(pi_rpc_client.subprocess, "Popen", fake_popen)

    await PiRpcClient.start(
        PiRpcStartRequest(
            command="pi",
            cwd=tmp_path / ".",
            env={"NATIVE_AGENT_PI_HOME": str(pi_home), "UNCHANGED": "1"},
        )
    )

    assert captured["env"]["NATIVE_AGENT_PI_HOME"] == str(pi_home)
    assert captured["env"]["HOME"] == str(pi_home)
    assert captured["env"]["USERPROFILE"] == str(pi_home)
    assert captured["env"]["UNCHANGED"] == "1"


@pytest.mark.asyncio
async def test_pi_rpc_client_start_appends_system_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeProcess:
        pid = 4321
        stdin = None
        stdout = None
        stderr = None
        returncode = 0

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(args: list[str], **kwargs: Any) -> FakeProcess:
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(pi_rpc_client, "resolve_cli_executable", lambda command, _cwd=None: command)
    monkeypatch.setattr(pi_rpc_client, "build_executable_invocation", lambda resolved: [resolved])
    monkeypatch.setattr(pi_rpc_client.subprocess, "Popen", fake_popen)

    await PiRpcClient.start(PiRpcStartRequest(
        command="pi",
        cwd=tmp_path / ".",
        append_system_prompt="solo prompt",
    ))

    assert captured["args"] == [
        "pi",
        "--mode",
        "rpc",
        "--append-system-prompt",
        "solo prompt",
    ]


@pytest.mark.asyncio
async def test_pi_rpc_client_start_sets_system_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeProcess:
        pid = 4321
        stdin = None
        stdout = None
        stderr = None
        returncode = 0

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(args: list[str], **kwargs: Any) -> FakeProcess:
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(pi_rpc_client, "resolve_cli_executable", lambda command, _cwd=None: command)
    monkeypatch.setattr(pi_rpc_client, "build_executable_invocation", lambda resolved: [resolved])
    monkeypatch.setattr(pi_rpc_client.subprocess, "Popen", fake_popen)

    await PiRpcClient.start(PiRpcStartRequest(
        command="pi",
        cwd=tmp_path / ".",
        system_prompt="全局提示",
        append_system_prompt="追加提示",
    ))

    assert captured["args"] == [
        "pi",
        "--mode",
        "rpc",
        "--system-prompt",
        "全局提示",
        "--append-system-prompt",
        "追加提示",
    ]
