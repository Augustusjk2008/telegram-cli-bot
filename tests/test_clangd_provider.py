from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bot.language_server.clangd import (
    ClangdProvider,
    discover_clangd_project_config,
    discover_compile_commands,
)
from bot.language_server.manager import (
    LanguageServerRuntime,
    LanguageServerRuntimeKey,
    LanguageServerRuntimeManager,
    _provider_for_request,
)


@pytest.mark.parametrize(
    ("path", "language_id"),
    [
        ("main.c", "c"),
        ("header.h", "cpp"),
        ("main.cc", "cpp"),
        ("main.cpp", "cpp"),
        ("main.cxx", "c++"),
        ("header.hh", "cpp"),
        ("header.hpp", "cpp"),
        ("header.hxx", "cpp"),
    ],
)
def test_clangd_provider_is_selected_for_supported_extensions(path: str, language_id: str) -> None:
    assert _provider_for_request({"document": {"path": path, "languageId": language_id}}) == "clangd"


def test_clangd_provider_rejects_unknown_language_id() -> None:
    assert _provider_for_request({"document": {"path": "main.cpp", "languageId": "typescript"}}) is None


def test_compile_commands_discovery_checks_root_and_common_build_directories(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    database = build / "compile_commands.json"
    database.write_text("[]\n", encoding="utf-8")

    assert discover_compile_commands(tmp_path) == database.resolve()


@pytest.mark.parametrize("config_name", [".clangd", "compile_flags.txt"])
def test_clangd_project_config_is_detected_without_parsing_workspace_content(
    tmp_path: Path,
    config_name: str,
) -> None:
    config = tmp_path / config_name
    config.write_text("CompileFlags:\n  Add: [-std=c++17]\n" if config_name == ".clangd" else "-std=c++17\n", encoding="utf-8")

    assert discover_clangd_project_config(tmp_path) == config.resolve()
    provider = ClangdProvider(tmp_path)
    assert provider.using_fallback_flags is False
    assert provider.fallback_flags == []


class FakeLspClient:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        return self.responses.get(method)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        self.notifications.append((method, params))


@pytest.mark.asyncio
async def test_clangd_initialize_uses_fallback_flags_and_capability() -> None:
    client = FakeLspClient(
        {
            "initialize": {
                "capabilities": {
                    "positionEncoding": "utf-8",
                    "implementationProvider": True,
                }
            }
        }
    )
    provider = ClangdProvider(Path.cwd())

    await provider.initialize(client)

    assert provider.position_encoding == "utf-8"
    assert provider.supports_implementation is True
    initialize = client.requests[0][1]
    assert initialize["initializationOptions"]["fallbackFlags"] == ["-std=c++17"]
    assert client.notifications == [("initialized", {})]


@pytest.mark.asyncio
async def test_clangd_navigates_workspace_locations_and_syncs_active_document(tmp_path: Path) -> None:
    source = tmp_path / "main.cpp"
    target = tmp_path / "service.hpp"
    source.write_text('#include "service.hpp"\nGreeter value;\n', encoding="utf-8")
    target.write_text("class Greeter {};\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "textDocument/definition": [
                {
                    "targetUri": target.as_uri(),
                    "targetRange": {
                        "start": {"line": 0, "character": 6},
                        "end": {"line": 0, "character": 13},
                    },
                    "targetSelectionRange": {
                        "start": {"line": 0, "character": 6},
                        "end": {"line": 0, "character": 13},
                    },
                }
            ]
        }
    )
    provider = ClangdProvider(tmp_path)
    provider.supports_implementation = True

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="cpp",
        version=3,
        content=source.read_text(encoding="utf-8"),
        line=2,
        column=1,
    )

    assert result[0]["path"] == "service.hpp"
    assert result[0]["selection_range"]["start"] == {"line": 1, "column": 7}
    assert client.notifications[0][0] == "textDocument/didOpen"
    assert client.requests[-1][0] == "textDocument/definition"
    assert client.requests[-1][1]["position"] == {"line": 1, "character": 0}


@pytest.mark.asyncio
async def test_clangd_implementation_is_capability_gated(tmp_path: Path) -> None:
    source = tmp_path / "main.cpp"
    source.write_text("value.run();\n", encoding="utf-8")
    client = FakeLspClient()
    provider = ClangdProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="implementation",
        path=source,
        language_id="cpp",
        version=1,
        content=source.read_text(encoding="utf-8"),
        line=1,
        column=7,
    )

    assert result == []
    assert client.requests == []
    assert client.notifications == []


def test_clangd_command_adds_only_trusted_provider_flags(tmp_path: Path) -> None:
    provider = ClangdProvider(tmp_path, runtime_cache_dir=tmp_path / "runtime-cache")
    command = provider.prepare_command(("clangd", "--stdio"))

    assert command[0] == "clangd"
    assert "--stdio" not in command
    assert "--background-index" in command
    assert "--background-index-priority=background" in command
    assert "--query-driver" not in " ".join(command)
    environment = provider.process_environment()
    assert environment is not None
    assert environment["XDG_CACHE_HOME"] == str((tmp_path / "runtime-cache").resolve())


@pytest.mark.parametrize("argument", ["--query-driver", "--query-driver=/usr/bin/**/g++-*"])
def test_clangd_rejects_query_driver_argument(tmp_path: Path, argument: str) -> None:
    provider = ClangdProvider(tmp_path)

    with pytest.raises(ValueError, match="query-driver"):
        provider.prepare_command(("clangd", "--stdio", argument))


@pytest.mark.asyncio
async def test_clangd_navigates_c_declaration_to_definition(tmp_path: Path) -> None:
    source = tmp_path / "main.c"
    target = tmp_path / "service.c"
    source.write_text('#include "service.h"\nint main(void) { return answer(); }\n', encoding="utf-8")
    target.write_text("int answer(void) { return 42; }\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "textDocument/definition": {
                "uri": target.as_uri(),
                "range": {
                    "start": {"line": 0, "character": 4},
                    "end": {"line": 0, "character": 10},
                },
            }
        }
    )
    provider = ClangdProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="c",
        version=1,
        content=source.read_text(encoding="utf-8"),
        line=2,
        column=31,
    )

    assert result[0]["path"] == "service.c"
    assert result[0]["selection_range"]["start"] == {"line": 1, "column": 5}


def test_clangd_runtime_uses_provider_and_runtime_cache(tmp_path: Path) -> None:
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "clangd"),
        ("clangd",),
        request_timeout=1,
        runtime_cache_dir=tmp_path / "cache",
    )

    assert isinstance(runtime.provider, ClangdProvider)
    assert "--background-index" in runtime.command
    assert runtime.provider.runtime_cache_dir == (tmp_path / "cache").resolve()


def test_manager_prewarm_accepts_clangd_without_navigation(tmp_path: Path) -> None:
    runtimes: list[SimpleNamespace] = []

    class Catalog:
        enabled = True

        @staticmethod
        def command_for(provider_id: str) -> tuple[str, ...] | None:
            assert provider_id == "clangd"
            return ("clangd",)

    def factory(key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> SimpleNamespace:
        runtime = SimpleNamespace(
            key=key,
            command=command,
            pending_count=0,
            active_operation_count=0,
            last_used_at=0.0,
            start=lambda: None,
            close=lambda: None,
            diagnostics=lambda: {"state": "ready", "open_document_count": 0},
        )
        # RuntimeProtocol methods are awaited by the manager.
        async def start() -> None:
            return None

        async def close() -> None:
            return None

        runtime.start = start
        runtime.close = close
        runtimes.append(runtime)
        return runtime

    manager = LanguageServerRuntimeManager(Catalog(), runtime_factory=factory)
    # This test focuses on provider selection; the real process smoke covers startup.
    import asyncio

    async def run() -> None:
        assert await manager.prewarm(
            bot_alias="main",
            user_id=1,
            workspace_root=tmp_path,
            provider_id="clangd",
        ) is True
        assert runtimes[0].key.provider_id == "clangd"
        await manager.shutdown()

    asyncio.run(run())


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_real_clangd_resolves_cpp_definition_when_enabled(tmp_path: Path) -> None:
    if os.environ.get("TCB_RUN_CLANGD_LSP_SMOKE", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("设置 TCB_RUN_CLANGD_LSP_SMOKE=1 后运行真实 clangd smoke")
    configured = os.environ.get("TCB_CLANGD_COMMAND", "").strip()
    command = tuple(configured.split()) if configured else None
    if command is None:
        clangd = shutil.which("clangd")
        if clangd:
            command = (clangd,)
    if command is None:
        managed = Path.home() / ".tcb" / "orbit-safe-claw" / "language-servers" / "native" / "clangd" / "current" / "bin" / "clangd.exe"
        if managed.is_file():
            command = (str(managed),)
    if command is None:
        pytest.skip("未发现 clangd")

    fixture = Path(__file__).parent / "fixtures" / "code_navigation" / "clangd"
    workspace = tmp_path / "clangd"
    shutil.copytree(fixture, workspace)
    source = workspace / "main.cpp"
    content = source.read_text(encoding="utf-8")
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, workspace.resolve(), "clangd"),
        command,
        request_timeout=10,
        runtime_cache_dir=tmp_path / "runtime-cache",
    )
    try:
        await runtime.start()
        cpp_result = await runtime.resolve_code_navigation(
            {
                "kind": "definition",
                "requestId": "clangd-smoke-definition",
                "document": {
                    "path": "main.cpp",
                    "languageId": "cpp",
                    "version": 1,
                    "content": content,
                },
                "position": {"line": 4, "column": 5},
            }
        )
        implementation_content = (workspace / "service.hpp").read_text(encoding="utf-8")
        implementation_result = await runtime.resolve_code_navigation(
            {
                "kind": "implementation",
                "requestId": "clangd-smoke-implementation",
                "document": {
                    "path": "service.hpp",
                    "languageId": "cpp",
                    "version": 1,
                    "content": implementation_content,
                },
                "position": {"line": 5, "column": 12},
            }
        )
        c_content = (workspace / "main.c").read_text(encoding="utf-8")
        c_result = await runtime.resolve_code_navigation(
            {
                "kind": "definition",
                "requestId": "clangd-smoke-c-definition",
                "document": {
                    "path": "main.c",
                    "languageId": "c",
                    "version": 1,
                    "content": c_content,
                },
                "position": {"line": 4, "column": 12},
            }
        )
    finally:
        await runtime.close()

    assert "service.hpp" in [str(item.get("path")) for item in cpp_result["items"]]
    assert "service.hpp" in [str(item.get("path")) for item in implementation_result["items"]]
    assert "service.h" in [str(item.get("path")) for item in c_result["items"]]
