from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

import bot.language_server.manager as manager_module
from bot.language_server.manager import (
    LanguageServerRuntime,
    LanguageServerRuntimeKey,
    LanguageServerRuntimeManager,
    LanguageServerUnavailableError,
)


class FakeCatalog:
    def __init__(self, command: tuple[str, ...] | None = ("fake-pyright", "--stdio"), *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.command = command

    def command_for(self, provider_id: str) -> tuple[str, ...] | None:
        assert provider_id == "pyright"
        return self.command


class FakeRuntime:
    def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> None:
        self.key = key
        self.command = command
        self.started = 0
        self.closed = 0
        self.requests: list[dict[str, Any]] = []
        self.pending_count = 0
        self.active_operation_count = 0
        self.open_document_count = 0

    async def start(self) -> None:
        self.started += 1

    async def resolve_code_navigation(self, request: dict[str, Any]) -> dict[str, object]:
        self.requests.append(request)
        return {
            "request_id": request["requestId"],
            "items": [{"provider": "pyright", "path": "target.py"}],
            "message": "",
        }

    async def close(self) -> None:
        self.closed += 1

    def diagnostics(self) -> dict[str, object]:
        return {
            "state": "ready",
            "pending_count": self.pending_count,
            "open_document_count": self.open_document_count,
        }


def _request(path: str = "main.py") -> dict[str, Any]:
    return {
        "kind": "definition",
        "requestId": "nav-1",
        "document": {
            "path": path,
            "languageId": "python",
            "version": 3,
            "content": "target()\n",
        },
        "position": {"line": 1, "column": 2},
    }


@pytest.mark.asyncio
async def test_manager_reuses_exact_isolation_key_and_separates_users(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)

    first = await manager.resolve_code_navigation(
        bot_alias="Main",
        user_id=101,
        workspace_root=tmp_path,
        request=_request(),
    )
    await manager.resolve_code_navigation(
        bot_alias="main",
        user_id=101,
        workspace_root=tmp_path / ".",
        request=_request(),
    )
    await manager.resolve_code_navigation(
        bot_alias="main",
        user_id=202,
        workspace_root=tmp_path,
        request=_request(),
    )

    assert first["items"] == [{"provider": "pyright", "path": "target.py"}]
    assert len(runtimes) == 2
    assert runtimes[0].started == 1
    assert len(runtimes[0].requests) == 2
    assert runtimes[0].key == LanguageServerRuntimeKey(
        bot_alias="main",
        user_id=101,
        workspace_root=tmp_path.resolve(),
        provider_id="pyright",
    )

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_serializes_concurrent_start_for_same_key(tmp_path: Path) -> None:
    created = 0
    release = asyncio.Event()

    class SlowRuntime(FakeRuntime):
        async def start(self) -> None:
            await release.wait()
            await super().start()

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> SlowRuntime:
        nonlocal created
        created += 1
        return SlowRuntime(key, command)

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)
    first = asyncio.create_task(
        manager.resolve_code_navigation(bot_alias="main", user_id=1, workspace_root=tmp_path, request=_request())
    )
    second = asyncio.create_task(
        manager.resolve_code_navigation(bot_alias="main", user_id=1, workspace_root=tmp_path, request=_request())
    )
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)

    assert created == 1
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_cancels_only_the_matching_navigation_request(tmp_path: Path) -> None:
    entered = asyncio.Event()

    class BlockingRuntime(FakeRuntime):
        async def resolve_code_navigation(self, request: dict[str, Any]) -> dict[str, object]:
            self.requests.append(request)
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=lambda key, command: BlockingRuntime(key, command),
    )
    pending = asyncio.create_task(
        manager.resolve_code_navigation(
            bot_alias="main",
            user_id=101,
            workspace_root=tmp_path,
            request=_request(),
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    assert await manager.cancel_code_navigation(
        bot_alias="main",
        user_id=202,
        workspace_root=tmp_path,
        request_id="nav-1",
    ) is False
    assert await manager.cancel_code_navigation(
        bot_alias="MAIN",
        user_id=101,
        workspace_root=tmp_path / ".",
        request_id="nav-1",
    ) is True

    result = await asyncio.gather(pending, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert manager.diagnostics()["active_request_count"] == 0
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_remembers_cancel_that_arrives_before_request_registration(tmp_path: Path) -> None:
    created = 0

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        nonlocal created
        created += 1
        return FakeRuntime(key, command)

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)

    assert await manager.cancel_code_navigation(
        bot_alias="main",
        user_id=101,
        workspace_root=tmp_path,
        request_id="nav-1",
    ) is False
    result = await asyncio.gather(
        manager.resolve_code_navigation(
            bot_alias="main",
            user_id=101,
            workspace_root=tmp_path,
            request=_request(),
        ),
        return_exceptions=True,
    )

    assert isinstance(result[0], asyncio.CancelledError)
    assert created == 0
    assert manager.diagnostics()["runtime_count"] == 0
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_reports_unavailable_without_starting_or_installing(tmp_path: Path) -> None:
    manager = LanguageServerRuntimeManager(FakeCatalog(command=None))

    with pytest.raises(LanguageServerUnavailableError, match="未安装"):
        await manager.resolve_code_navigation(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            request=_request(),
        )

    assert manager.diagnostics()["runtime_count"] == 0


@pytest.mark.asyncio
async def test_manager_does_not_evict_a_runtime_with_an_active_navigation_operation(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        max_runtimes=1,
    )
    await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )
    runtimes[0].active_operation_count = 1

    with pytest.raises(RuntimeError, match="实例数量已达上限"):
        await manager.prewarm(
            bot_alias="main",
            user_id=2,
            workspace_root=tmp_path,
            provider_id="pyright",
        )

    assert runtimes[0].closed == 0
    assert manager.diagnostics()["runtime_count"] == 1
    runtimes[0].active_operation_count = 0
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_ignores_unsupported_language_requests(tmp_path: Path) -> None:
    manager = LanguageServerRuntimeManager(FakeCatalog())
    request = _request("main.rs")
    request["document"]["languageId"] = "rust"

    result = await manager.resolve_code_navigation(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        request=request,
    )

    assert result == {"request_id": "nav-1", "items": [], "message": "未找到语义定义"}
    assert manager.diagnostics()["runtime_count"] == 0


@pytest.mark.asyncio
async def test_manager_shutdown_closes_all_runtimes_and_exposes_diagnostics(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)
    await manager.resolve_code_navigation(bot_alias="main", user_id=1, workspace_root=tmp_path, request=_request())
    await manager.resolve_code_navigation(bot_alias="secondary", user_id=1, workspace_root=tmp_path, request=_request())

    diagnostics = manager.diagnostics()
    report = await manager.shutdown()

    assert diagnostics["runtime_count"] == 2
    assert diagnostics["provider_counts"] == {"pyright": 2}
    assert report == {"requested": 2, "closed": 2, "failed": 0}
    assert [runtime.closed for runtime in runtimes] == [1, 1]
    assert manager.diagnostics()["runtime_count"] == 0


@pytest.mark.asyncio
async def test_manager_runs_fake_lsp_process_and_shuts_it_down_normally(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    target = tmp_path / "helper.py"
    source.write_text("old_name()\n", encoding="utf-8")
    target.write_text("def renamed():\n    return None\n", encoding="utf-8")
    fake_server = tmp_path / "fake_pyright.py"
    fake_server.write_text(
        r'''
import json
import sys
from pathlib import Path


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(2)
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])).decode("utf-8"))


def send(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload)
    sys.stdout.buffer.flush()


initialize = read_message()
assert initialize["method"] == "initialize"
send({
    "jsonrpc": "2.0",
    "id": initialize["id"],
    "result": {"capabilities": {"positionEncoding": "utf-16", "implementationProvider": True}},
})
assert read_message()["method"] == "initialized"
assert read_message()["method"] == "workspace/didChangeConfiguration"
opened = read_message()
assert opened["method"] == "textDocument/didOpen"
assert "renamed" in opened["params"]["textDocument"]["text"]
definition = read_message()
assert definition["method"] == "textDocument/definition"
send({
    "jsonrpc": "2.0",
    "id": definition["id"],
    "result": {
        "uri": (Path.cwd() / "helper.py").resolve().as_uri(),
        "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 11}},
    },
})
shutdown = read_message()
assert shutdown["method"] == "shutdown"
send({"jsonrpc": "2.0", "id": shutdown["id"], "result": None})
assert read_message()["method"] == "exit"
''',
        encoding="utf-8",
    )
    catalog = FakeCatalog((sys.executable, "-u", str(fake_server)))
    manager = LanguageServerRuntimeManager(catalog, request_timeout=2)
    request = _request()
    request["document"]["content"] = "def renamed():\n    return None\n\nrenamed()\n"
    request["position"] = {"line": 4, "column": 2}

    result = await manager.resolve_code_navigation(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        request=request,
    )
    report = await manager.shutdown()

    assert result["items"][0]["path"] == "helper.py"
    assert result["items"][0]["selection_range"]["start"] == {"line": 1, "column": 5}
    assert report == {"requested": 1, "closed": 1, "failed": 0}


@pytest.mark.asyncio
async def test_manager_prewarms_only_discovered_pyright_without_navigation(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)

    first = await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )
    second = await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )

    assert first is True
    assert second is True
    assert len(runtimes) == 1
    assert runtimes[0].requests == []
    assert manager.runtime_status(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )["state"] == "ready"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_prewarms_discovered_typescript_without_navigation(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    class TypeScriptCatalog:
        enabled = True

        @staticmethod
        def command_for(provider_id: str) -> tuple[str, ...] | None:
            assert provider_id == "typescript"
            return ("typescript-language-server", "--stdio")

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(TypeScriptCatalog(), runtime_factory=factory)

    assert await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="typescript",
    ) is True
    assert len(runtimes) == 1
    assert runtimes[0].key.provider_id == "typescript"
    assert runtimes[0].requests == []
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_prewarm_does_not_start_or_install_missing_service(tmp_path: Path) -> None:
    manager = LanguageServerRuntimeManager(FakeCatalog(command=None))

    assert await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    ) is False
    assert manager.diagnostics()["runtime_count"] == 0


@pytest.mark.asyncio
async def test_manager_shutdown_closes_runtime_cancelled_during_start(tmp_path: Path) -> None:
    entered = asyncio.Event()
    runtime_holder: list[FakeRuntime] = []

    class BlockingRuntime(FakeRuntime):
        async def start(self) -> None:
            entered.set()
            await asyncio.Event().wait()

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> BlockingRuntime:
        runtime = BlockingRuntime(key, command)
        runtime_holder.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)
    prewarm = asyncio.create_task(
        manager.prewarm(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        )
    )
    await entered.wait()

    await manager.shutdown()
    result = await asyncio.gather(prewarm, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert runtime_holder[0].closed == 1


@pytest.mark.asyncio
async def test_runtime_tracks_lsp_work_done_progress_as_indexing(tmp_path: Path) -> None:
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright"),
        ("fake-pyright",),
        request_timeout=1,
    )
    runtime.state = "ready"

    await runtime.handle_notification(
        "$/progress",
        {"token": "pyright-index", "value": {"kind": "begin", "title": "索引工作区"}},
    )
    assert runtime.diagnostics()["state"] == "indexing"

    await runtime.handle_notification(
        "$/progress",
        {"token": "pyright-index", "value": {"kind": "end", "message": "完成"}},
    )
    assert runtime.diagnostics()["state"] == "ready"


@pytest.mark.asyncio
async def test_runtime_allows_navigation_while_server_reports_indexing(tmp_path: Path) -> None:
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright"),
        ("fake-pyright",),
        request_timeout=1,
    )
    runtime.state = "indexing"
    runtime.client = object()

    class StubProvider:
        open_document_count = 0

        async def navigate(self, _client: object, **_kwargs: Any) -> list[dict[str, object]]:
            return []

    runtime.provider = StubProvider()  # type: ignore[assignment]

    result = await runtime.resolve_code_navigation(_request())

    assert result["items"] == []


@pytest.mark.asyncio
async def test_runtime_counts_the_full_navigation_operation_as_active(tmp_path: Path) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright"),
        ("fake-pyright",),
        request_timeout=1,
    )
    runtime.state = "ready"
    runtime.client = object()

    class StubProvider:
        open_document_count = 0
        supports_implementation = False

        async def navigate(self, _client: object, **_kwargs: Any) -> list[dict[str, object]]:
            entered.set()
            await release.wait()
            return []

    runtime.provider = StubProvider()  # type: ignore[assignment]
    navigation = asyncio.create_task(runtime.resolve_code_navigation(_request()))

    await asyncio.wait_for(entered.wait(), timeout=1)
    assert runtime.diagnostics()["active_operation_count"] == 1
    release.set()
    await navigation
    assert runtime.diagnostics()["active_operation_count"] == 0


@pytest.mark.asyncio
async def test_runtime_close_forces_process_tree_after_total_grace_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HangingClient:
        async def request(self, *_args: Any, **_kwargs: Any) -> None:
            await asyncio.Event().wait()

        async def notify(self, *_args: Any, **_kwargs: Any) -> None:
            await asyncio.Event().wait()

        async def close(self, *_args: Any, **_kwargs: Any) -> None:
            await asyncio.Event().wait()

    class HangingProcess:
        pid = 123
        returncode: int | None = None

        async def wait(self) -> int:
            await asyncio.Event().wait()
            return 0

    terminated: list[object] = []

    async def fake_terminate(process: object) -> None:
        terminated.append(process)
        process.returncode = -9  # type: ignore[attr-defined]

    monkeypatch.setattr(manager_module, "terminate_async_process_tree", fake_terminate)
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright"),
        ("fake-pyright",),
        request_timeout=0.1,
    )
    process = HangingProcess()
    runtime.state = "ready"
    runtime.client = HangingClient()
    runtime.process = process  # type: ignore[assignment]

    await asyncio.wait_for(runtime.close(), timeout=0.5)

    assert terminated == [process]
    assert runtime.process is None
    assert runtime.state == "stopped"
