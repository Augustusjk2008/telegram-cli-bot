from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import bot.language_server.manager as manager_module
from bot.language_server.document_store import LanguageDocument
from bot.language_server.external_source_registry import ExternalSourceNotFoundError, ExternalSourceRegistry
from bot.language_server.jsonrpc import (
    LspJsonRpcClient,
    LspJsonRpcClosedError,
    LspJsonRpcProtocolError,
)
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
        self.synced_documents: list[LanguageDocument] = []
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

    async def sync_documents(self, documents: list[LanguageDocument]) -> list[LanguageDocument]:
        self.synced_documents.extend(documents)
        return list(documents)

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


def _external_request(source_id: str, *, path: str = "python-site-packages/package.py") -> dict[str, Any]:
    return {
        "kind": "definition",
        "requestId": "external-nav-1",
        "document": {
            "sourceId": source_id,
            "path": path,
            "languageId": "python",
            "version": 99,
            "content": "browser content must not be trusted",
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
async def test_manager_resolves_external_source_id_by_scope_without_storing_browser_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    dependency = tmp_path / "dependency"
    workspace.mkdir()
    dependency.mkdir()
    target = dependency / "package.py"
    target.write_text("value = 1\n", encoding="utf-8")
    registry = ExternalSourceRegistry(enabled=True)
    record = registry.register(
        target,
        alias="main",
        user_id=7,
        workspace_root=workspace,
        provider_id="pyright",
        approved_roots=[dependency],
    )
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        external_source_registry=registry,
    )
    request = _external_request(record.source_id)

    result = await manager.resolve_code_navigation(
        bot_alias="main",
        user_id=7,
        workspace_root=workspace,
        request=request,
    )

    key = LanguageServerRuntimeKey("main", 7, workspace.resolve(), "pyright")
    assert result["request_id"] == "external-nav-1"
    assert runtimes[0].key == key
    assert manager.document_store.snapshot(key) == ()
    with pytest.raises(ExternalSourceNotFoundError):
        await manager.resolve_code_navigation(
            bot_alias="main",
            user_id=8,
            workspace_root=workspace,
            request=_external_request(record.source_id),
        )
    with pytest.raises(ValueError, match="绝对路径"):
        await manager.resolve_code_navigation(
            bot_alias="main",
            user_id=7,
            workspace_root=workspace,
            request=_external_request(record.source_id, path=str(target)),
        )
    with pytest.raises(ValueError, match="绝对路径"):
        await manager.resolve_code_navigation(
            bot_alias="main",
            user_id=7,
            workspace_root=workspace,
            request=_external_request(str(target)),
        )
    await manager.shutdown()


@pytest.mark.asyncio
async def test_runtime_reads_external_source_from_registry_not_browser_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    dependency = tmp_path / "dependency"
    workspace.mkdir()
    dependency.mkdir()
    target = dependency / "package.py"
    target.write_text("value = 1\n", encoding="utf-8")
    registry = ExternalSourceRegistry(enabled=True)
    record = registry.register(
        target,
        alias="main",
        user_id=7,
        workspace_root=workspace,
        provider_id="pyright",
        approved_roots=[dependency],
    )
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 7, workspace.resolve(), "pyright"),
        ("fake-pyright",),
        request_timeout=1,
        external_source_registry=registry,
    )
    runtime.state = "ready"
    runtime.client = object()
    calls: list[dict[str, Any]] = []

    class StubProvider:
        open_document_count = 0
        supports_implementation = False

        async def navigate(self, _client: object, **kwargs: Any) -> list[dict[str, object]]:
            calls.append(kwargs)
            return []

    runtime.provider = StubProvider()  # type: ignore[assignment]
    await runtime.resolve_code_navigation(_external_request(record.source_id))

    assert calls[0]["path"] == target.resolve()
    assert calls[0]["content"] == target.read_bytes().decode("utf-8")
    assert calls[0]["source_id"] == record.source_id


@pytest.mark.asyncio
async def test_manager_closes_open_external_source_by_scoped_source_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    dependency = tmp_path / "dependency"
    workspace.mkdir()
    dependency.mkdir()
    target = dependency / "package.py"
    target.write_text("value = 1\n", encoding="utf-8")
    registry = ExternalSourceRegistry(enabled=True)
    record = registry.register(
        target,
        alias="main",
        user_id=7,
        workspace_root=workspace,
        provider_id="pyright",
        approved_roots=[dependency],
    )

    class ExternalCloseRuntime(FakeRuntime):
        async def close_external_sources(self, source_ids: list[str]) -> list[str]:
            self.closed_external = list(source_ids)
            return list(source_ids)

    runtimes: list[ExternalCloseRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> ExternalCloseRuntime:
        runtime = ExternalCloseRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        external_source_registry=registry,
    )
    await manager.resolve_code_navigation(
        bot_alias="main",
        user_id=7,
        workspace_root=workspace,
        request=_external_request(record.source_id),
    )

    result = await manager.close_documents(
        bot_alias="main",
        user_id=7,
        workspace_root=workspace,
        documents=[{"sourceId": record.source_id}],
    )

    assert result["closed"] == 1
    assert result["documents"] == [{"sourceId": record.source_id}]
    assert runtimes[0].closed_external == [record.source_id]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_rejects_absolute_and_external_source_documents_from_sync_endpoints(tmp_path: Path) -> None:
    manager = LanguageServerRuntimeManager(FakeCatalog())

    with pytest.raises(ValueError, match="绝对路径"):
        await manager.sync_documents(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            documents=[{"path": str(tmp_path / "outside.py"), "languageId": "python", "version": 1, "content": "x"}],
        )
    with pytest.raises(ValueError, match="外部源码为只读"):
        await manager.sync_documents(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            documents=[{"sourceId": "src_fake", "languageId": "python", "version": 1, "content": "x"}],
        )
    dependency_request = _request("node_modules/package/index.ts")
    dependency_request["document"]["languageId"] = "typescript"
    with pytest.raises(ValueError, match="必须使用 source_id"):
        await manager.resolve_code_navigation(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            request=dependency_request,
        )
    with pytest.raises(ValueError, match="绝对路径"):
        await manager.close_documents(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            documents=[{"path": str(tmp_path / "outside.py")}],
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


@pytest.mark.asyncio
async def test_runtime_replays_document_store_snapshots_when_started(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)
    key = LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright")
    document = LanguageDocument.from_value(_request()["document"])
    manager.document_store.sync_documents(key, [document])

    assert await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    ) is True

    assert runtimes[0].synced_documents == [document]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_evicts_idle_runtime_after_idle_timeout(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        idle_timeout=0.01,
        max_runtimes=2,
    )
    await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )
    runtimes[0].last_used_at = time.monotonic() - 1

    assert await manager.evict_idle() == 1
    assert runtimes[0].closed == 1
    assert manager.diagnostics()["runtime_count"] == 0
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_restart_runtime_replaces_only_the_requested_scope(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeRuntime:
        runtime = FakeRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(FakeCatalog(), runtime_factory=factory)
    await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )
    await manager.prewarm(
        bot_alias="main",
        user_id=2,
        workspace_root=tmp_path,
        provider_id="pyright",
    )
    key = LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright")
    document = LanguageDocument.from_value(_request()["document"])
    manager.document_store.sync_documents(key, [document])

    await manager.restart_runtime(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )

    assert len(runtimes) == 3
    assert runtimes[0].closed == 1
    assert runtimes[1].closed == 0
    assert runtimes[2].started == 1
    assert runtimes[2].synced_documents == [document]
    assert manager.runtime_status(
        bot_alias="main",
        user_id=2,
        workspace_root=tmp_path,
        provider_id="pyright",
    ) is not None
    await manager.shutdown()


class _MemoryWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.frame_written = asyncio.Event()
        self.closed = False

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)
        self.frame_written.set()

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _MemoryProcess:
    def __init__(self) -> None:
        self.stdin = _MemoryWriter()
        self.stdout = asyncio.StreamReader()
        self.returncode: int | None = None


class _ExitWatchingProcess(_MemoryProcess):
    def __init__(self) -> None:
        super().__init__()
        self.exited = asyncio.Event()

    async def wait(self) -> int:
        await self.exited.wait()
        return int(self.returncode or 0)


@pytest.mark.asyncio
async def test_jsonrpc_stdout_eof_fails_pending_request_immediately() -> None:
    process = _MemoryProcess()
    client = LspJsonRpcClient(process, request_timeout_seconds=5)
    pending = asyncio.create_task(client.request("textDocument/definition"))
    await asyncio.wait_for(process.stdin.frame_written.wait(), timeout=1)

    process.stdout.feed_eof()

    with pytest.raises(LspJsonRpcClosedError, match="stdout"):
        await asyncio.wait_for(pending, timeout=0.2)
    assert client.pending_count == 0
    await client.close()


@pytest.mark.asyncio
async def test_jsonrpc_protocol_corruption_fails_pending_request_immediately() -> None:
    process = _MemoryProcess()
    client = LspJsonRpcClient(process, request_timeout_seconds=5)
    pending = asyncio.create_task(client.request("textDocument/definition"))
    await asyncio.wait_for(process.stdin.frame_written.wait(), timeout=1)

    process.stdout.feed_data(b"Content-Length: 1\r\n\r\n{")

    with pytest.raises(LspJsonRpcProtocolError, match="有效 UTF-8 JSON"):
        await asyncio.wait_for(pending, timeout=0.2)
    assert client.pending_count == 0
    await client.close()


@pytest.mark.asyncio
async def test_jsonrpc_process_exit_fails_pending_request_before_stdout_eof() -> None:
    process = _ExitWatchingProcess()
    client = LspJsonRpcClient(process, request_timeout_seconds=5)
    pending = asyncio.create_task(client.request("textDocument/definition"))
    await asyncio.wait_for(process.stdin.frame_written.wait(), timeout=1)

    process.returncode = 9
    process.exited.set()

    with pytest.raises(LspJsonRpcClosedError, match="进程已退出"):
        await asyncio.wait_for(pending, timeout=0.2)
    assert client.pending_count == 0
    await client.close()


@pytest.mark.asyncio
async def test_runtime_keeps_only_a_bounded_stderr_tail(tmp_path: Path) -> None:
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright"),
        ("fake-pyright",),
        request_timeout=1,
    )
    stream = asyncio.StreamReader()
    drain = asyncio.create_task(runtime._drain_stderr(stream))
    stream.feed_data("\n".join(f"error-{index}" for index in range(80)).encode("utf-8") + b"\n")
    stream.feed_eof()
    await asyncio.wait_for(drain, timeout=1)

    tail = runtime.diagnostics()["stderr_tail"]
    assert isinstance(tail, list)
    assert len(tail) <= 40
    assert tail[-1] == "error-79"


@pytest.mark.asyncio
async def test_manager_discards_old_generation_navigation_result_and_retries_once(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    class StaleRuntime(FakeRuntime):
        def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...], *, stale: bool) -> None:
            super().__init__(key, command)
            self.state = "stopped"
            self.stale = stale

        async def start(self) -> None:
            self.started += 1
            self.state = "ready"

        async def resolve_code_navigation(self, request: dict[str, Any]) -> dict[str, object]:
            self.requests.append(request)
            if self.stale:
                self.state = "error"
                handler = getattr(self, "_failure_handler")
                await handler(self, RuntimeError("旧 runtime 已失效"))
                return {
                    "request_id": request["requestId"],
                    "items": [{"provider": "stale"}],
                    "message": "",
                }
            return {
                "request_id": request["requestId"],
                "items": [{"provider": "fresh"}],
                "message": "",
            }

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> StaleRuntime:
        runtime = StaleRuntime(key, command, stale=not runtimes)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        restart_base_delay=0,
        restart_max_delay=0,
    )
    result = await manager.resolve_code_navigation(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        request=_request(),
    )

    assert result["items"] == [{"provider": "fresh"}]
    assert len(runtimes) == 2
    assert manager.diagnostics()["restart_count"] == 1
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_enters_degraded_after_three_crashes_in_the_window(tmp_path: Path) -> None:
    runtimes: list[FakeRuntime] = []

    class CrashRuntime(FakeRuntime):
        def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...], *, fail_start: bool) -> None:
            super().__init__(key, command)
            self.fail_start = fail_start
            self.state = "stopped"

        async def start(self) -> None:
            self.started += 1
            if self.fail_start:
                self.state = "error"
                raise RuntimeError("启动崩溃")
            self.state = "ready"

        async def close(self) -> None:
            self.closed += 1
            self.state = "stopped"

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> CrashRuntime:
        runtime = CrashRuntime(key, command, fail_start=bool(runtimes))
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        restart_base_delay=0,
        restart_max_delay=0,
    )
    await manager.prewarm(
        bot_alias="main",
        user_id=1,
        workspace_root=tmp_path,
        provider_id="pyright",
    )
    first = runtimes[0]
    await manager._on_runtime_failure(first, RuntimeError("进程退出"))
    for _ in range(20):
        if manager.diagnostics()["degraded_count"]:
            break
        await asyncio.sleep(0.01)

    diagnostics = manager.diagnostics()
    assert diagnostics["degraded_count"] == 1
    assert diagnostics["crash_count"] == 3
    assert diagnostics["recent_errors"]
    with pytest.raises(LanguageServerUnavailableError, match="降级"):
        await manager.prewarm(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        )
    await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (LspJsonRpcClosedError, "语言服务器 stdout 已关闭"),
        (LspJsonRpcClosedError, "语言服务器进程已退出 (code=9)"),
        (LspJsonRpcProtocolError, "LSP JSON-RPC 消息不是有效 UTF-8 JSON"),
    ],
    ids=("stdout-eof", "process-exit", "invalid-frame"),
)
async def test_manager_recovers_initialize_transport_failures_then_degrades_after_three_crashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
    message: str,
) -> None:
    """首次 initialize 期间的传输失败也必须进入 runtime 恢复状态机。"""

    runtimes: list[FakeRuntime] = []
    restart_delays: list[float] = []
    original_sleep = asyncio.sleep
    third_start = asyncio.Event()

    async def record_backoff(delay: float, *_args: object, **_kwargs: object) -> None:
        restart_delays.append(delay)
        await original_sleep(0)

    class InitializeTransportFailureRuntime(FakeRuntime):
        def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> None:
            super().__init__(key, command)
            self.state = "stopped"

        async def start(self) -> None:
            self.started += 1
            self.state = "starting"
            if len(runtimes) >= 3:
                third_start.set()
            error = error_type(message)
            handler = getattr(self, "_failure_handler")
            await handler(self, error)
            self.state = "error"
            raise error

        async def close(self) -> None:
            self.closed += 1
            if self.state != "degraded":
                self.state = "stopped"

        def diagnostics(self) -> dict[str, object]:
            return {
                **super().diagnostics(),
                "state": self.state,
                "restart_attempts": getattr(self, "restart_attempts", 0),
            }

    def factory(
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> InitializeTransportFailureRuntime:
        runtime = InitializeTransportFailureRuntime(key, command)
        runtimes.append(runtime)
        return runtime

    # 记录等待值，而非实际等待，避免用时间精度测试指数退避。
    monkeypatch.setattr(manager_module.asyncio, "sleep", record_backoff)
    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        restart_base_delay=0.25,
        restart_max_delay=1,
    )
    try:
        with pytest.raises(error_type, match=re.escape(message)):
            await manager.prewarm(
                bot_alias="main",
                user_id=1,
                workspace_root=tmp_path,
                provider_id="pyright",
            )

        await asyncio.wait_for(third_start.wait(), timeout=0.2)
        for _ in range(10):
            if manager.diagnostics()["degraded_count"] == 1:
                break
            await original_sleep(0)

        diagnostics = manager.diagnostics()
        assert diagnostics["crash_count"] == 3
        assert diagnostics["degraded_count"] == 1
        assert restart_delays[:2] == [0.25, 0.5]
        with pytest.raises(LanguageServerUnavailableError, match="降级"):
            await manager.prewarm(
                bot_alias="main",
                user_id=1,
                workspace_root=tmp_path,
                provider_id="pyright",
            )
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_retries_idempotent_navigation_once_when_first_initialize_fails(tmp_path: Path) -> None:
    """首次 runtime initialize 失败时，定义跳转只能以新 generation 重试一次。"""

    runtimes: list[FakeRuntime] = []

    class InitializingNavigationRuntime(FakeRuntime):
        def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...], *, fails: bool) -> None:
            super().__init__(key, command)
            self.fails = fails
            self.state = "stopped"

        async def start(self) -> None:
            self.started += 1
            self.state = "starting"
            if self.fails:
                error = LspJsonRpcClosedError("语言服务器 stdout 已关闭")
                handler = getattr(self, "_failure_handler")
                await handler(self, error)
                self.state = "error"
                raise error
            self.state = "ready"

        async def close(self) -> None:
            self.closed += 1
            if self.state != "degraded":
                self.state = "stopped"

        def diagnostics(self) -> dict[str, object]:
            return {**super().diagnostics(), "state": self.state}

    def factory(
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> InitializingNavigationRuntime:
        runtime = InitializingNavigationRuntime(key, command, fails=not runtimes)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        restart_base_delay=0,
        restart_max_delay=0,
    )
    try:
        result = await manager.resolve_code_navigation(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            request=_request(),
        )

        assert result["items"] == [{"provider": "pyright", "path": "target.py"}]
        assert len(runtimes) == 2
        assert [runtime.started for runtime in runtimes] == [1, 1]
        assert sum(len(runtime.requests) for runtime in runtimes) == 1
        assert manager.diagnostics()["crash_count"] == 1
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (LspJsonRpcClosedError, "语言服务器 stdout 已关闭"),
        (LspJsonRpcProtocolError, "LSP JSON-RPC 消息不是有效 UTF-8 JSON"),
    ],
    ids=("stdout-eof", "invalid-frame"),
)
async def test_manager_recovers_when_replay_reports_transport_failure_before_runtime_registration(
    tmp_path: Path,
    error_type: type[BaseException],
    message: str,
) -> None:
    """replay 的失败回调不能让刚启动的 generation 被错误注册为 ready。"""

    runtimes: list[FakeRuntime] = []
    failure_reported = asyncio.Event()
    replacement_started = asyncio.Event()

    class ReplayFailureRuntime(FakeRuntime):
        def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...], *, fails_replay: bool) -> None:
            super().__init__(key, command)
            self.fails_replay = fails_replay
            self.state = "stopped"

        async def start(self) -> None:
            self.started += 1
            self.state = "ready"
            if not self.fails_replay:
                replacement_started.set()

        async def sync_documents(self, documents: list[LanguageDocument]) -> list[LanguageDocument]:
            self.synced_documents.extend(documents)
            if self.fails_replay:
                failure_reported.set()
                handler = getattr(self, "_failure_handler")
                await handler(self, error_type(message))
            return list(documents)

        async def close(self) -> None:
            self.closed += 1
            if self.state != "degraded":
                self.state = "stopped"

        def diagnostics(self) -> dict[str, object]:
            return {**super().diagnostics(), "state": self.state}

    def factory(
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> ReplayFailureRuntime:
        runtime = ReplayFailureRuntime(key, command, fails_replay=not runtimes)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        restart_base_delay=0,
        restart_max_delay=0,
    )
    key = LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright")
    manager.document_store.sync_documents(key, [LanguageDocument.from_value(_request()["document"])])
    prewarm = asyncio.create_task(
        manager.prewarm(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        )
    )
    try:
        await asyncio.wait_for(failure_reported.wait(), timeout=0.2)
        await asyncio.wait_for(replacement_started.wait(), timeout=0.2)
        await asyncio.gather(prewarm, return_exceptions=True)

        status = manager.runtime_status(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        )
        assert status is not None
        assert status["state"] == "ready"
        assert status["generation"] == 2
        assert manager.diagnostics()["crash_count"] == 1
        assert manager.diagnostics()["restart_count"] == 1
        assert len(runtimes) == 2
        assert runtimes[0].state != "ready"
    finally:
        if not prewarm.done():
            prewarm.cancel()
            await asyncio.gather(prewarm, return_exceptions=True)
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (LspJsonRpcClosedError, "语言服务器 stdout 已关闭"),
        (LspJsonRpcProtocolError, "LSP JSON-RPC 消息不是有效 UTF-8 JSON"),
    ],
    ids=("stdout-eof", "invalid-frame"),
)
async def test_manager_recovers_when_replacement_replay_reports_transport_failure(
    tmp_path: Path,
    error_type: type[BaseException],
    message: str,
) -> None:
    """自动 recovery 的 replacement 也必须在 replay 失败后继续下一 generation。"""

    runtimes: list[FakeRuntime] = []
    replacement_failure_reported = asyncio.Event()
    third_generation_started = asyncio.Event()

    class ReplacementReplayFailureRuntime(FakeRuntime):
        def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...], *, fails_replay: bool) -> None:
            super().__init__(key, command)
            self.fails_replay = fails_replay
            self.state = "stopped"

        async def start(self) -> None:
            self.started += 1
            self.state = "ready"
            if len(runtimes) == 3:
                third_generation_started.set()

        async def sync_documents(self, documents: list[LanguageDocument]) -> list[LanguageDocument]:
            self.synced_documents.extend(documents)
            if self.fails_replay:
                replacement_failure_reported.set()
                handler = getattr(self, "_failure_handler")
                await handler(self, error_type(message))
            return list(documents)

        async def close(self) -> None:
            self.closed += 1
            if self.state != "degraded":
                self.state = "stopped"

        def diagnostics(self) -> dict[str, object]:
            return {**super().diagnostics(), "state": self.state}

    def factory(
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> ReplacementReplayFailureRuntime:
        runtime = ReplacementReplayFailureRuntime(key, command, fails_replay=len(runtimes) == 1)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        restart_base_delay=0,
        restart_max_delay=0,
    )
    key = LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright")
    try:
        assert await manager.prewarm(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        ) is True
        assert manager.runtime_status(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        )["state"] == "ready"
        manager.document_store.sync_documents(key, [LanguageDocument.from_value(_request()["document"])])

        first_failure_handler = getattr(runtimes[0], "_failure_handler")
        await first_failure_handler(runtimes[0], LspJsonRpcClosedError("首个 runtime 已退出"))

        await asyncio.wait_for(replacement_failure_reported.wait(), timeout=0.2)
        await asyncio.wait_for(third_generation_started.wait(), timeout=0.2)
        for _ in range(10):
            status = manager.runtime_status(
                bot_alias="main",
                user_id=1,
                workspace_root=tmp_path,
                provider_id="pyright",
            )
            if status is not None and status.get("state") == "ready" and status.get("generation") == 3:
                break
            await asyncio.sleep(0)

        status = manager.runtime_status(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        )
        assert status is not None
        assert status["state"] == "ready"
        assert status["generation"] == 3
        assert manager.diagnostics()["crash_count"] == 2
        assert manager.diagnostics()["restart_count"] == 1
        assert len(runtimes) == 3
        assert runtimes[1].state != "ready"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_closes_uncommitted_replacement_when_automatic_restart_is_cancelled(tmp_path: Path) -> None:
    """restart 在提交 replacement 前被取消时，候选进程和候选表都必须清理。"""

    runtimes: list[FakeRuntime] = []
    replacement_replay_started = asyncio.Event()
    allow_replacement_replay_to_finish = asyncio.Event()

    class CancellableReplacementRuntime(FakeRuntime):
        def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...], *, blocks_replay: bool) -> None:
            super().__init__(key, command)
            self.blocks_replay = blocks_replay
            self.state = "stopped"

        async def start(self) -> None:
            self.started += 1
            self.state = "ready"

        async def sync_documents(self, documents: list[LanguageDocument]) -> list[LanguageDocument]:
            self.synced_documents.extend(documents)
            if self.blocks_replay:
                replacement_replay_started.set()
                await allow_replacement_replay_to_finish.wait()
            return list(documents)

        async def close(self) -> None:
            self.closed += 1
            if self.state != "degraded":
                self.state = "stopped"

        def diagnostics(self) -> dict[str, object]:
            return {**super().diagnostics(), "state": self.state}

    def factory(
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> CancellableReplacementRuntime:
        runtime = CancellableReplacementRuntime(key, command, blocks_replay=len(runtimes) == 1)
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(
        FakeCatalog(),
        runtime_factory=factory,
        restart_base_delay=0,
        restart_max_delay=0,
    )
    key = LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright")
    test_holds_lock = False
    restart_task: asyncio.Task[None] | None = None
    try:
        assert await manager.prewarm(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="pyright",
        ) is True
        manager.document_store.sync_documents(key, [LanguageDocument.from_value(_request()["document"])])

        first_failure_handler = getattr(runtimes[0], "_failure_handler")
        await first_failure_handler(runtimes[0], LspJsonRpcClosedError("首个 runtime 已退出"))
        await asyncio.wait_for(replacement_replay_started.wait(), timeout=0.2)

        await manager._lock.acquire()
        test_holds_lock = True
        allow_replacement_replay_to_finish.set()
        for _ in range(20):
            waiters = getattr(manager._lock, "_waiters", ()) or ()
            if any(not waiter.done() for waiter in waiters):
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("replacement 未在提交前等待 manager 锁")

        restart_task = manager._restart_tasks[key]
        assert not restart_task.done()
        restart_task.cancel()
        manager._lock.release()
        test_holds_lock = False
        await asyncio.gather(restart_task, return_exceptions=True)

        assert runtimes[1].closed == 1
        assert key not in manager._replacement_initializing_runtimes
        assert key not in manager._replacement_initialization_failures
        assert key not in manager._restart_tasks
    finally:
        allow_replacement_replay_to_finish.set()
        if test_holds_lock:
            manager._lock.release()
        if restart_task is not None and not restart_task.done():
            restart_task.cancel()
            await asyncio.gather(restart_task, return_exceptions=True)
        await manager.shutdown()
