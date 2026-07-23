from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bot.language_server.manager import (
    LanguageServerRuntime,
    LanguageServerRuntimeKey,
    LanguageServerRuntimeManager,
    _provider_for_request,
)
from bot.language_server.typescript import TypeScriptProvider
from bot.runtime_paths import get_language_server_node_tools_dir


@pytest.mark.parametrize(
    ("path", "language_id"),
    [
        ("main.ts", "typescript"),
        ("component.tsx", "typescriptreact"),
        ("main.js", "javascript"),
        ("component.jsx", "javascriptreact"),
        ("module.mts", "typescript"),
        ("module.cts", "typescript"),
        ("module.mjs", "javascript"),
        ("module.cjs", "javascript"),
    ],
)
def test_typescript_provider_is_selected_for_supported_ts_js_extensions(
    path: str,
    language_id: str,
) -> None:
    assert _provider_for_request({"document": {"path": path, "languageId": language_id}}) == "typescript"


def test_typescript_runtime_uses_a_typescript_provider(tmp_path) -> None:
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "typescript"),
        ("typescript-language-server", "--stdio"),
        request_timeout=1,
    )

    assert type(runtime.provider).__name__ == "TypeScriptProvider"


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


def _write_tsserver(package_root: Path) -> Path:
    tsserver = package_root / "lib" / "tsserver.js"
    tsserver.parent.mkdir(parents=True)
    tsserver.write_text("// test TypeScript SDK\n", encoding="utf-8")
    return tsserver.resolve()


@pytest.mark.asyncio
async def test_typescript_initialize_prefers_project_sdk_and_disables_downloads_and_plugins(
    tmp_path: Path,
) -> None:
    project_sdk = _write_tsserver(tmp_path / "node_modules" / "typescript")
    managed_sdk = _write_tsserver(tmp_path / "managed" / "typescript")
    client = FakeLspClient(
        {
            "initialize": {
                "capabilities": {
                    "positionEncoding": "utf-16",
                    "implementationProvider": True,
                }
            }
        }
    )
    provider = TypeScriptProvider(tmp_path, managed_sdk_path=managed_sdk)

    await provider.initialize(client)

    method, params = client.requests[0]
    assert method == "initialize"
    assert params["rootUri"] == tmp_path.resolve().as_uri()
    assert params["workspaceFolders"] == [{"uri": tmp_path.resolve().as_uri(), "name": tmp_path.name}]
    assert params["initializationOptions"] == {
        "tsserver": {"path": str(project_sdk), "fallbackPath": str(managed_sdk)},
        "disableAutomaticTypingAcquisition": True,
        "plugins": [],
    }
    assert client.notifications == [("initialized", {})]
    assert provider.position_encoding == "utf-16"
    assert provider.supports_implementation is True


@pytest.mark.asyncio
async def test_typescript_initialize_uses_managed_sdk_as_fallback_without_a_project_sdk(tmp_path: Path) -> None:
    managed_sdk = _write_tsserver(tmp_path / "managed" / "typescript")
    client = FakeLspClient({"initialize": {"capabilities": {}}})
    provider = TypeScriptProvider(tmp_path, managed_sdk_path=managed_sdk)

    await provider.initialize(client)

    assert client.requests[0][1]["initializationOptions"]["tsserver"] == {
        "fallbackPath": str(managed_sdk)
    }


@pytest.mark.asyncio
async def test_typescript_uses_source_definition_command_when_server_advertises_it(tmp_path: Path) -> None:
    source = tmp_path / "main.ts"
    target = tmp_path / "service.ts"
    source.write_text('import { Service } from "./service";\nnew Service();\n', encoding="utf-8")
    target.write_text("export class Service {}\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "initialize": {
                "capabilities": {
                    "definitionProvider": True,
                    "executeCommandProvider": {
                        "commands": ["_typescript.goToSourceDefinition"],
                    },
                }
            },
            "workspace/executeCommand": {
                "uri": target.resolve().as_uri(),
                "range": {
                    "start": {"line": 0, "character": 13},
                    "end": {"line": 0, "character": 20},
                },
            },
        }
    )
    provider = TypeScriptProvider(tmp_path)
    await provider.initialize(client)

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="typescript",
        version=1,
        content=source.read_text(encoding="utf-8"),
        line=1,
        column=10,
    )

    assert result[0]["path"] == "service.ts"
    assert client.requests[1] == (
        "workspace/executeCommand",
        {
            "command": "_typescript.goToSourceDefinition",
            "arguments": [
                source.resolve().as_uri(),
                {"line": 0, "character": 9},
            ],
        },
    )


@pytest.mark.asyncio
async def test_typescript_primes_configured_project_before_implementation_request(tmp_path: Path) -> None:
    source = tmp_path / "contracts.ts"
    target = tmp_path / "service.ts"
    source.write_text("export interface Service {\n  run(): void;\n}\n", encoding="utf-8")
    target.write_text("export class ServiceImpl {\n  run(): void {}\n}\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "initialize": {
                "capabilities": {
                    "implementationProvider": True,
                    "executeCommandProvider": {
                        "commands": ["typescript.tsserverRequest"],
                    },
                }
            },
            "workspace/executeCommand": {"success": True},
            "textDocument/implementation": {
                "uri": target.resolve().as_uri(),
                "range": {
                    "start": {"line": 1, "character": 2},
                    "end": {"line": 1, "character": 5},
                },
            },
        }
    )
    provider = TypeScriptProvider(tmp_path)
    await provider.initialize(client)

    result = await provider.navigate(
        client,
        kind="implementation",
        path=source,
        language_id="typescript",
        version=1,
        content=source.read_text(encoding="utf-8"),
        line=2,
        column=3,
    )

    assert result[0]["path"] == "service.ts"
    assert [method for method, _params in client.requests] == [
        "initialize",
        "workspace/executeCommand",
        "textDocument/implementation",
    ]
    assert client.requests[1][1] == {
        "command": "typescript.tsserverRequest",
        "arguments": [
            "projectInfo",
            {"file": source.resolve().as_uri(), "needFileNameList": False},
            {},
        ],
    }


def test_manager_wires_managed_typescript_sdk_from_catalog(tmp_path: Path) -> None:
    tools_root = tmp_path / "node-tools"
    managed_sdk = _write_tsserver(tools_root / "node_modules" / "typescript")
    catalog = SimpleNamespace(
        enabled=True,
        installer=SimpleNamespace(node_tools_dir=tools_root),
    )
    manager = LanguageServerRuntimeManager(catalog)

    runtime = manager._create_runtime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "typescript"),
        ("typescript-language-server", "--stdio"),
    )

    assert runtime.provider.managed_sdk_path == managed_sdk


@pytest.mark.asyncio
@pytest.mark.parametrize("config_name", ["tsconfig.json", "jsconfig.json", None])
async def test_typescript_initializes_configured_and_inferred_workspaces_without_overriding_project_config(
    tmp_path: Path,
    config_name: str | None,
) -> None:
    if config_name is not None:
        (tmp_path / config_name).write_text('{"compilerOptions": {"strict": true}}\n', encoding="utf-8")
    client = FakeLspClient({"initialize": {"capabilities": {}}})
    provider = TypeScriptProvider(tmp_path)

    await provider.initialize(client)

    params = client.requests[0][1]
    assert params["rootPath"] == str(tmp_path.resolve())
    assert params["rootUri"] == tmp_path.resolve().as_uri()
    assert params["workspaceFolders"] == [{"uri": tmp_path.resolve().as_uri(), "name": tmp_path.name}]
    assert "project" not in params["initializationOptions"]


@pytest.mark.asyncio
async def test_typescript_syncs_javascript_snapshot_with_monotonic_versions(tmp_path: Path) -> None:
    source = tmp_path / "main.js"
    source.write_text("run()\n", encoding="utf-8")
    client = FakeLspClient({"textDocument/definition": None})
    provider = TypeScriptProvider(tmp_path)

    await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="javascript",
        version=8,
        content="firstRun()\n",
        line=1,
        column=2,
    )
    await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="javascript",
        version=1,
        content="secondRun()\n",
        line=1,
        column=2,
    )

    assert client.notifications[0] == (
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": source.resolve().as_uri(),
                "languageId": "javascript",
                "version": 8,
                "text": "firstRun()\n",
            }
        },
    )
    assert client.notifications[1][0] == "textDocument/didChange"
    assert client.notifications[1][1]["textDocument"]["version"] == 9
    assert client.requests[0][0] == "textDocument/definition"


@pytest.mark.asyncio
async def test_typescript_normalizes_location_links_with_utf16_emoji_prefix(tmp_path: Path) -> None:
    source = tmp_path / "main.ts"
    target = tmp_path / "target.ts"
    source.write_text("target\n", encoding="utf-8")
    target.write_text("😀target = 1\n", encoding="utf-8")
    target_uri = target.resolve().as_uri()
    client = FakeLspClient(
        {
            "textDocument/definition": {
                "targetUri": target_uri,
                "targetRange": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 12},
                },
                "targetSelectionRange": {
                    "start": {"line": 0, "character": 2},
                    "end": {"line": 0, "character": 8},
                },
            }
        }
    )
    provider = TypeScriptProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="typescript",
        version=1,
        content="😀target\n",
        line=1,
        column=2,
    )

    assert client.requests[0][1]["position"] == {"line": 0, "character": 2}
    assert result == [
        {
            "target_type": "workspace",
            "path": "target.ts",
            "provider": "typescript",
            "range": {
                "start": {"line": 1, "column": 1},
                "end": {"line": 1, "column": 12},
            },
            "selection_range": {
                "start": {"line": 1, "column": 2},
                "end": {"line": 1, "column": 8},
            },
        }
    ]


@pytest.mark.asyncio
async def test_typescript_does_not_fake_implementation_when_server_capability_is_absent(tmp_path: Path) -> None:
    source = tmp_path / "main.ts"
    source.write_text("run()\n", encoding="utf-8")
    client = FakeLspClient({"textDocument/implementation": [{"unexpected": True}]})
    provider = TypeScriptProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="implementation",
        path=source,
        language_id="typescript",
        version=1,
        content="run()\n",
        line=1,
        column=2,
    )

    assert result == []
    assert client.requests == []


@pytest.mark.asyncio
async def test_typescript_rejects_node_modules_location_until_external_source_support_exists(tmp_path: Path) -> None:
    source = tmp_path / "main.ts"
    dependency = tmp_path / "node_modules" / "package" / "index.d.ts"
    source.write_text("run()\n", encoding="utf-8")
    dependency.parent.mkdir(parents=True)
    dependency.write_text("export declare function run(): void;\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "textDocument/definition": {
                "uri": dependency.resolve().as_uri(),
                "range": {
                    "start": {"line": 0, "character": 24},
                    "end": {"line": 0, "character": 27},
                },
            }
        }
    )
    provider = TypeScriptProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="typescript",
        version=1,
        content="run()\n",
        line=1,
        column=2,
    )

    assert result == []


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "code_navigation" / "typescript"


@pytest.mark.parametrize(
    ("fixture_name", "config_name", "required_paths"),
    [
        (
            "tsconfig",
            "tsconfig.json",
            ("src/main.ts", "src/index.ts", "src/contracts.ts", "src/service.ts"),
        ),
        ("jsconfig", "jsconfig.json", ("src/main.js", "src/module.js")),
        ("inferred", None, ("main.ts", "module.ts")),
    ],
)
def test_typescript_navigation_fixtures_cover_configured_and_inferred_projects(
    fixture_name: str,
    config_name: str | None,
    required_paths: tuple[str, ...],
) -> None:
    root = FIXTURE_ROOT / fixture_name

    assert root.is_dir()
    assert (root / config_name).is_file() if config_name is not None else not (root / "tsconfig.json").exists()
    assert all((root / path).is_file() for path in required_paths)


def _smoke_command() -> tuple[str, ...] | None:
    node = shutil.which("node")
    tools_root = _smoke_node_tools_dir()
    cli = tools_root / "node_modules" / "typescript-language-server" / "lib" / "cli.mjs"
    if not node or not cli.is_file():
        return None
    return (node, str(cli), "--stdio")


def _managed_sdk_for_smoke() -> Path | None:
    candidate = _smoke_node_tools_dir() / "node_modules" / "typescript" / "lib" / "tsserver.js"
    return candidate.resolve() if candidate.is_file() else None


def _smoke_node_tools_dir() -> Path:
    configured = os.environ.get("TCB_TYPESCRIPT_LSP_NODE_TOOLS_DIR", "").strip()
    return Path(configured).expanduser() if configured else get_language_server_node_tools_dir()


def _one_based_position(content: str, symbol: str) -> dict[str, int]:
    before = content[: content.index(symbol)]
    return {"line": before.count("\n") + 1, "column": len(before.rsplit("\n", 1)[-1]) + 1}


@pytest.mark.smoke
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture_name", "source_path", "symbol", "kind", "expected_path"),
    [
        ("tsconfig", "src/main.ts", "ConcreteGreeter", "definition", "src/service.ts"),
        ("tsconfig", "src/contracts.ts", "greet", "implementation", "src/service.ts"),
        ("jsconfig", "src/main.js", "formatName", "definition", "src/module.js"),
        ("inferred", "main.ts", "inferredValue", "definition", "module.ts"),
    ],
)
async def test_real_typescript_language_server_resolves_navigation_fixtures(
    tmp_path: Path,
    fixture_name: str,
    source_path: str,
    symbol: str,
    kind: str,
    expected_path: str,
) -> None:
    if os.environ.get("TCB_RUN_TYPESCRIPT_LSP_SMOKE", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("设置 TCB_RUN_TYPESCRIPT_LSP_SMOKE=1 后运行真实 TypeScript LSP smoke")
    command = _smoke_command()
    managed_sdk = _managed_sdk_for_smoke()
    if command is None or managed_sdk is None:
        pytest.skip("未发现已安装的托管 TypeScript Language Server 与 SDK")
    workspace = tmp_path / fixture_name
    shutil.copytree(FIXTURE_ROOT / fixture_name, workspace)
    source = workspace / source_path
    content = source.read_text(encoding="utf-8")
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, workspace.resolve(), "typescript"),
        command,
        request_timeout=10,
        managed_typescript_sdk_path=managed_sdk,
    )
    try:
        await runtime.start()
        result = await runtime.resolve_code_navigation(
            {
                "kind": kind,
                "requestId": f"smoke-{fixture_name}-{kind}",
                "document": {
                    "path": source_path,
                    "languageId": "javascript" if source.suffix == ".js" else "typescript",
                    "version": 1,
                    "content": content,
                },
                "position": _one_based_position(content, symbol),
            }
        )
    finally:
        await runtime.close()

    assert expected_path in [str(item.get("path")) for item in result["items"]]
