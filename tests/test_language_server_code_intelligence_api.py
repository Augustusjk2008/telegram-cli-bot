"""Code-intelligence queries through the runtime manager and the Web API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from bot.language_server.manager import (
    LanguageServerRuntime,
    LanguageServerRuntimeKey,
    LanguageServerRuntimeManager,
)
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_READ_FILE_CONTENT
from bot.web.server import WebApiServer


CAPABILITIES: dict[str, Any] = {
    "textDocumentSync": {"openClose": True, "change": 1},
    "hoverProvider": True,
    "definitionProvider": True,
    "referencesProvider": True,
    "documentSymbolProvider": True,
    "completionProvider": {"triggerCharacters": ["."]},
}


def _lsp_range(start_line: int, start_character: int, end_line: int, end_character: int) -> dict[str, Any]:
    return {
        "start": {"line": start_line, "character": start_character},
        "end": {"line": end_line, "character": end_character},
    }


class FakeLspClient:
    pending_count = 0

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        if method == "initialize":
            return {"capabilities": CAPABILITIES}
        response = self.responses.get(method)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            response = response(params)
        if hasattr(response, "__await__"):
            response = await response
        return response

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        self.notifications.append((method, params))

    def count(self, method: str) -> int:
        return sum(1 for name, _params in self.requests if name == method)


class FakeProcessRuntime(LanguageServerRuntime):
    """The real runtime and provider with the subprocess replaced by a fake client."""

    def __init__(self, key: LanguageServerRuntimeKey, command: tuple[str, ...], client: FakeLspClient) -> None:
        super().__init__(key, command, request_timeout=5.0)
        self._fake_client = client

    async def start(self) -> None:
        self.client = self._fake_client
        await self.provider.initialize(self.client)
        self.state = "ready"

    async def close(self) -> None:
        self.client = None
        self.state = "stopped"


class FakeCatalog:
    installer = None

    def __init__(self, *, enabled: bool = True, commands: dict[str, tuple[str, ...]] | None = None) -> None:
        self.enabled = enabled
        self.commands = {"clangd": ("clangd",), "pyright": ("pyright-langserver", "--stdio")} if commands is None else commands

    def command_for(self, provider_id: str) -> tuple[str, ...] | None:
        return self.commands.get(provider_id)

    def api_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "providers": [{"id": "pyright", "status": "available"}, {"id": "clangd", "status": "available"}],
        }


class Harness:
    def __init__(self, workspace: Path, responses: dict[str, Any] | None = None, **catalog: Any) -> None:
        self.workspace = workspace
        self.client = FakeLspClient(responses if responses is not None else {})
        self.runtimes: list[FakeProcessRuntime] = []
        self.manager = LanguageServerRuntimeManager(
            FakeCatalog(**catalog),
            runtime_factory=self._create,
            request_timeout=5.0,
            idle_timeout=300.0,
        )

    def _create(self, key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> FakeProcessRuntime:
        runtime = FakeProcessRuntime(key, command, self.client)
        self.runtimes.append(runtime)
        return runtime

    @property
    def runtime(self) -> FakeProcessRuntime:
        return self.runtimes[-1]

    async def query(self, request: dict[str, Any]) -> dict[str, object]:
        return await self.manager.query_code_intelligence(
            bot_alias="main",
            user_id=7,
            workspace_root=self.workspace,
            request=request,
        )

    async def publish(self, path: str, diagnostics: list[dict[str, Any]], version: int | None = None) -> None:
        params: dict[str, Any] = {"uri": (self.workspace / path).as_uri(), "diagnostics": diagnostics}
        if version is not None:
            params["version"] = version
        await self.runtime.handle_notification("textDocument/publishDiagnostics", params)


def _request(kind: str, content: str = "int add(int a, int b);\n", **extra: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "kind": kind,
        "requestId": extra.pop("request_id", "req-1"),
        "document": {
            "path": extra.pop("path", "main.cpp"),
            "languageId": extra.pop("language_id", "cpp"),
            "version": extra.pop("version", 1),
            "content": content,
        },
    }
    request.update(extra)
    return request


HOVER = {"contents": {"kind": "markdown", "value": "`int add(int, int)`"}, "range": _lsp_range(0, 4, 0, 7)}


@pytest_asyncio.fixture
async def harness(tmp_path: Path):
    instance = Harness(tmp_path, {"textDocument/hover": HOVER})
    yield instance
    await instance.manager.shutdown()


# -- manager --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_returns_the_common_envelope_and_kind_payload(harness: Harness) -> None:
    result = await harness.query(_request("hover", position={"line": 1, "column": 5}))

    assert result == {
        "request_id": "req-1",
        "kind": "hover",
        "provider": "clangd",
        "available": True,
        "supported": True,
        "message": "",
        "contents": [{"kind": "markdown", "value": "`int add(int, int)`"}],
        "range": {"start": {"line": 1, "column": 5}, "end": {"line": 1, "column": 8}},
    }
    # The query went through the shared document store, like navigation.
    stored = harness.manager.document_store.get(harness.runtime.key, "main.cpp")
    assert stored is not None and stored.version == 1

    # Kind is matched case-insensitively and ``request_id`` is accepted too.
    request = _request("HOVER", position={"line": 1, "column": 5})
    request["request_id"] = request.pop("requestId")
    assert (await harness.query(request))["kind"] == "hover"


@pytest.mark.asyncio
async def test_unsupported_capability_and_missing_provider_are_not_errors(harness: Harness) -> None:
    unsupported = await harness.query(_request("semanticTokens"))
    assert unsupported == {
        "request_id": "req-1",
        "kind": "semanticTokens",
        "provider": "clangd",
        "available": True,
        "supported": False,
        "message": "",
        "legend": {"types": [], "modifiers": []},
        "tokens": [],
        "truncated": False,
        "inactive_ranges": [],
        "version": None,
    }

    no_provider = await harness.query(_request("documentSymbols", path="notes.md", language_id="markdown"))
    assert no_provider == {
        "request_id": "req-1",
        "kind": "documentSymbols",
        "provider": "",
        "available": False,
        "supported": False,
        "message": "",
        "items": [],
        "truncated": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog", [{"enabled": False}, {"commands": {}}])
async def test_unavailable_language_service_reports_available_false(tmp_path: Path, catalog: dict[str, Any]) -> None:
    instance = Harness(tmp_path, {"textDocument/hover": HOVER}, **catalog)
    try:
        result = await instance.query(_request("completion", position={"line": 1, "column": 1}))
    finally:
        await instance.manager.shutdown()

    assert result["available"] is False and result["supported"] is False
    assert result["provider"] == "clangd" and result["kind"] == "completion"
    assert result["items"] == [] and result["is_incomplete"] is False
    assert isinstance(result["message"], str) and result["message"]
    assert instance.runtimes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda request: request.update(kind="rename"),
        lambda request: request.update(requestId=" "),
        lambda request: request.pop("position"),
        lambda request: request.update(document="main.cpp"),
        lambda request: request["document"].update(path="/etc/passwd.cpp"),
        lambda request: request["document"].update(path="../outside.cpp"),
        lambda request: request["document"].update(languageId=""),
    ],
)
async def test_invalid_requests_raise_value_error(harness: Harness, mutate: Any) -> None:
    request = _request("hover", position={"line": 1, "column": 1})
    mutate(request)

    with pytest.raises(ValueError):
        await harness.query(request)


@pytest.mark.asyncio
async def test_request_timeout_reports_indexing(tmp_path: Path) -> None:
    instance = Harness(tmp_path, {"textDocument/references": asyncio.TimeoutError()})
    try:
        result = await instance.query(_request("references", position={"line": 1, "column": 5}))
    finally:
        await instance.manager.shutdown()

    assert result["message"] == "仍在索引"
    assert result["available"] is True and result["supported"] is True
    assert result["items"] == [] and result["truncated"] is False


@pytest.mark.asyncio
async def test_diagnostics_wait_for_the_current_version_without_blocking_the_document(harness: Harness) -> None:
    content = "int a = b;\n"
    task = asyncio.create_task(harness.query(_request("diagnostics", content, waitMs=4000)))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if harness.runtimes and harness.runtime.provider.open_document_count:
            break
    assert not task.done()

    # The wait holds no document lock: other requests for the same file still run.
    hover = await asyncio.wait_for(
        harness.query(_request("hover", content, request_id="req-2", position={"line": 1, "column": 5})),
        timeout=1.0,
    )
    assert hover["supported"] is True
    assert harness.runtime.active_operation_count == 1

    await harness.publish("main.cpp", [{"range": _lsp_range(0, 8, 0, 9), "severity": 1, "message": "undeclared b"}], version=1)
    result = await asyncio.wait_for(task, timeout=1.0)

    assert result["ready"] is True and result["version"] == 1
    assert result["items"] == [
        {
            "range": {"start": {"line": 1, "column": 9}, "end": {"line": 1, "column": 10}},
            "severity": "error",
            "message": "undeclared b",
            "source": "",
            "code": "",
        }
    ]
    assert "_pending_diagnostics" not in result
    assert harness.runtime.active_operation_count == 0

    # Unchanged content with stored diagnostics answers immediately, even with a long wait.
    again = await asyncio.wait_for(harness.query(_request("diagnostics", content, waitMs=4000)), timeout=0.5)
    assert again["ready"] is True and len(again["items"]) == 1


@pytest.mark.asyncio
async def test_diagnostics_report_not_ready_when_nothing_arrives(harness: Harness) -> None:
    immediate = await asyncio.wait_for(harness.query(_request("diagnostics")), timeout=0.5)
    assert immediate["ready"] is False and immediate["items"] == [] and immediate["version"] is None

    waited = await harness.query(_request("diagnostics", waitMs=60))
    assert waited["ready"] is False and "_pending_diagnostics" not in waited

    # waitMs is clamped rather than rejected.
    clamped = await asyncio.wait_for(harness.query(_request("diagnostics", waitMs=-500)), timeout=0.5)
    assert clamped["ready"] is False


@pytest.mark.asyncio
async def test_closing_a_document_forgets_its_diagnostics(harness: Harness) -> None:
    await harness.query(_request("diagnostics"))
    await harness.publish("main.cpp", [{"range": _lsp_range(0, 0, 0, 3), "message": "x"}], version=1)
    assert (await harness.query(_request("diagnostics")))["ready"] is True

    closed = await harness.manager.close_documents(
        bot_alias="main",
        user_id=7,
        workspace_root=harness.workspace,
        documents=[{"path": "main.cpp", "languageId": "cpp", "version": 1}],
    )
    assert closed["closed"] == 1

    reopened = await harness.query(_request("diagnostics", version=2))
    assert reopened["ready"] is False and reopened["items"] == []


@pytest.mark.asyncio
async def test_external_source_diagnostics_are_empty_and_ready(tmp_path: Path) -> None:
    instance = Harness(tmp_path)
    resolved: list[tuple[str, dict[str, Any]]] = []

    class Registry:
        def resolve(self, source_id: str, **scope: Any) -> Any:
            resolved.append((source_id, scope))
            return SimpleNamespace(provider_id="clangd")

    instance.manager.external_source_registry = Registry()  # type: ignore[assignment]
    try:
        result = await instance.query(
            {"kind": "diagnostics", "requestId": "req-9", "document": {"sourceId": "src-1", "languageId": "cpp"}, "waitMs": 3000}
        )
    finally:
        await instance.manager.shutdown()

    assert result == {
        "request_id": "req-9",
        "kind": "diagnostics",
        "provider": "clangd",
        "available": True,
        "supported": True,
        "message": "",
        "items": [],
        "version": None,
        "ready": True,
    }
    assert resolved[0][0] == "src-1" and resolved[0][1]["alias"] == "main" and resolved[0][1]["user_id"] == 7
    assert instance.runtimes == []


@pytest.mark.asyncio
async def test_queries_are_cancelled_through_the_navigation_cancel_endpoint(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def never(_params: dict[str, Any]) -> None:
        started.set()
        await asyncio.Event().wait()

    instance = Harness(tmp_path, {"textDocument/hover": lambda params: never(params)})
    try:
        task = asyncio.create_task(instance.query(_request("hover", request_id="slow", position={"line": 1, "column": 5})))
        await asyncio.wait_for(started.wait(), timeout=1.0)

        cancelled = await instance.manager.cancel_code_navigation(
            bot_alias="main",
            user_id=7,
            workspace_root=tmp_path,
            request_id="slow",
        )

        assert cancelled is True
        with pytest.raises(asyncio.CancelledError):
            await task
        # The marker also rejects a late arrival of the same request ID.
        with pytest.raises(asyncio.CancelledError):
            await instance.query(_request("hover", request_id="slow", position={"line": 1, "column": 5}))
    finally:
        await instance.manager.shutdown()


@pytest.mark.asyncio
async def test_navigation_still_resolves_through_the_shared_request_path(tmp_path: Path) -> None:
    uri = (tmp_path / "main.cpp").as_uri()
    instance = Harness(tmp_path, {"textDocument/definition": [{"uri": uri, "range": _lsp_range(0, 4, 0, 7)}]})
    request = {**_request("definition", "int add(int a, int b);\nint x = add(1, 2);\n"), "position": {"line": 2, "column": 9}}
    try:
        result = await instance.manager.resolve_code_navigation(
            bot_alias="main", user_id=7, workspace_root=tmp_path, request=request,
        )
        no_provider = await instance.manager.resolve_code_navigation(
            bot_alias="main",
            user_id=7,
            workspace_root=tmp_path,
            request={**request, "document": {**request["document"], "path": "notes.md", "languageId": "markdown"}},
        )
        with pytest.raises(ValueError, match="代码导航类型无效"):
            await instance.manager.resolve_code_navigation(
                bot_alias="main", user_id=7, workspace_root=tmp_path, request={**request, "kind": "hover"},
            )
        with pytest.raises(ValueError, match="代码导航请求格式无效"):
            await instance.manager.resolve_code_navigation(
                bot_alias="main", user_id=7, workspace_root=tmp_path, request={**request, "document": None},
            )
    finally:
        await instance.manager.shutdown()

    span = {"start": {"line": 1, "column": 5}, "end": {"line": 1, "column": 8}}
    assert result == {
        "request_id": "req-1",
        "items": [
            {"target_type": "workspace", "path": "main.cpp", "provider": "clangd", "range": span, "selection_range": span}
        ],
        "message": "",
    }
    assert no_provider == {"request_id": "req-1", "items": [], "message": "未找到语义定义"}


# -- Web API --------------------------------------------------------------------------------


class DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    def snapshot(self) -> dict[str, object]:
        return {"mode": "disabled", "status": "stopped", "source": "disabled", "public_url": "", "last_error": ""}


def _build_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, workspace: Path, instance: Harness) -> WebApiServer:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(alias="main", cli_type="codex", cli_path="codex", working_dir=str(workspace)),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(
        manager,
        host="127.0.0.1",
        port=8765,
        tunnel_service=DummyTunnelService(),
        language_server_catalog=instance.manager.catalog,
        language_server_installer=object(),
        language_server_manager=instance.manager,
    )

    async def reader(_request: Any, capability: str) -> AuthContext:
        assert capability == CAP_READ_FILE_CONTENT
        return AuthContext(user_id=7, token_used=True, capabilities={CAP_READ_FILE_CONTENT})

    monkeypatch.setattr(server, "_with_capability", reader)
    monkeypatch.setattr(server, "_workspace_file_root", lambda _alias, _auth: str(workspace))
    return server


QUERY_URL = "/api/bots/main/workspace/code-intelligence/query"


@pytest.mark.asyncio
async def test_query_endpoint_answers_and_rejects_bad_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instance = Harness(workspace, {"textDocument/hover": HOVER})
    server = _build_server(monkeypatch, tmp_path, workspace, instance)

    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(QUERY_URL, json=_request("hover", position={"line": 1, "column": 5}))
            body = await response.json()
            bad_kind = await client.post(QUERY_URL, json=_request("rename"))
            bad_kind_body = await bad_kind.json()
            no_position = await client.post(QUERY_URL, json=_request("completion"))
            no_position_body = await no_position.json()
            not_object = await client.post(QUERY_URL, json=["hover"])
    await instance.manager.shutdown()

    assert response.status == 200
    assert body["ok"] is True
    assert body["data"]["request_id"] == "req-1" and body["data"]["kind"] == "hover"
    assert body["data"]["provider"] == "clangd"
    assert body["data"]["available"] is True and body["data"]["supported"] is True
    assert body["data"]["contents"] == [{"kind": "markdown", "value": "`int add(int, int)`"}]
    assert body["data"]["range"] == {"start": {"line": 1, "column": 5}, "end": {"line": 1, "column": 8}}

    assert bad_kind.status == 400
    assert bad_kind_body["error"]["code"] == "invalid_code_intelligence_request"
    assert no_position.status == 400
    assert no_position_body["error"]["code"] == "invalid_code_intelligence_request"
    assert not_object.status == 400


@pytest.mark.asyncio
async def test_query_endpoint_maps_unavailable_and_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    disabled = Harness(workspace, enabled=False)
    server = _build_server(monkeypatch, tmp_path, workspace, disabled)

    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            unavailable = await client.post(QUERY_URL, json=_request("documentSymbols"))
            unavailable_body = await unavailable.json()

            async def broken(**_kwargs: Any) -> dict[str, object]:
                raise RuntimeError("secret /path/detail")

            monkeypatch.setattr(disabled.manager, "query_code_intelligence", broken)
            failed = await client.post(QUERY_URL, json=_request("documentSymbols"))
            failed_body = await failed.json()

            async def superseded(**_kwargs: Any) -> dict[str, object]:
                raise asyncio.CancelledError

            monkeypatch.setattr(disabled.manager, "query_code_intelligence", superseded)
            stale = await client.post(QUERY_URL, json=_request("documentSymbols"))
            stale_body = await stale.json()
    await disabled.manager.shutdown()

    assert unavailable.status == 200
    assert unavailable_body["data"]["available"] is False and unavailable_body["data"]["supported"] is False
    assert unavailable_body["data"]["items"] == [] and unavailable_body["data"]["kind"] == "documentSymbols"

    assert failed.status == 503
    assert failed_body["error"]["code"] == "language_server_failed"
    assert "secret" not in json.dumps(failed_body, ensure_ascii=False)

    assert stale.status == 409
    assert stale_body["error"]["code"] == "code_intelligence_superseded"


@pytest.mark.asyncio
async def test_language_server_status_describes_clangd_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instance = Harness(workspace)
    server = _build_server(monkeypatch, tmp_path, workspace, instance)
    url = "/api/bots/main/workspace/language-servers"

    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            fallback = {item["id"]: item for item in (await (await client.get(url)).json())["data"]["providers"]}
            (workspace / "build").mkdir()
            (workspace / "build" / "compile_commands.json").write_text("[]", encoding="utf-8")
            configured = {item["id"]: item for item in (await (await client.get(url)).json())["data"]["providers"]}
    await instance.manager.shutdown()

    assert fallback["clangd"]["configuration"]["mode"] == "fallback"
    assert fallback["clangd"]["configuration"]["summary"] == "默认参数 -std=c++17"
    assert "compile_commands.json" in fallback["clangd"]["configuration"]["hint"]
    assert "configuration" not in fallback["pyright"]
    assert configured["clangd"]["configuration"] == {
        "mode": "compile_commands",
        "summary": "compile_commands.json (build)",
        "hint": "",
    }
