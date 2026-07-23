from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from typing import Any

import pytest

from bot.language_server.document_store import LanguageDocument
from bot.language_server.pyright import PyrightProvider, discover_python_interpreter


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


def _touch_interpreter(root: Path) -> Path:
    relative = Path("Scripts/python.exe") if sys.platform == "win32" else Path("bin/python")
    executable = root / relative
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    return executable


def test_discover_python_interpreter_prefers_workspace_dot_venv(tmp_path: Path) -> None:
    dot_venv_python = _touch_interpreter(tmp_path / ".venv")
    _touch_interpreter(tmp_path / "venv")
    fallback = tmp_path / "fallback-python"
    fallback.write_bytes(b"")

    assert discover_python_interpreter(tmp_path, current_executable=fallback) == dot_venv_python.resolve()


def test_pyright_answers_workspace_folder_and_configuration_server_requests(tmp_path: Path) -> None:
    interpreter = _touch_interpreter(tmp_path / ".venv")
    provider = PyrightProvider(tmp_path)

    folders = provider.handle_server_request("workspace/workspaceFolders", None)
    settings = provider.handle_server_request(
        "workspace/configuration",
        {"items": [{"section": "python"}, {"section": "python.analysis"}]},
    )

    assert folders == [{"uri": tmp_path.resolve().as_uri(), "name": tmp_path.name}]
    assert provider.discovered_python_interpreter == interpreter.resolve()
    assert settings[0]["pythonPath"] == str(Path(sys.executable).resolve())
    assert settings[1]["diagnosticMode"] == "openFilesOnly"


@pytest.mark.asyncio
async def test_pyright_initializes_workspace_and_configures_selected_interpreter(tmp_path: Path) -> None:
    workspace_interpreter = _touch_interpreter(tmp_path / ".venv")
    trusted_interpreter = tmp_path / "trusted-python.exe"
    trusted_interpreter.write_bytes(b"")
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
    provider = PyrightProvider(tmp_path, current_executable=trusted_interpreter)

    await provider.initialize(client)

    method, params = client.requests[0]
    assert method == "initialize"
    assert params["rootUri"] == tmp_path.resolve().as_uri()
    assert params["workspaceFolders"] == [{"uri": tmp_path.resolve().as_uri(), "name": tmp_path.name}]
    assert params["capabilities"]["general"]["positionEncodings"] == ["utf-16", "utf-8"]
    assert params["capabilities"]["workspace"]["configuration"] is False
    assert params["capabilities"]["window"]["workDoneProgress"] is True
    assert client.notifications[0] == ("initialized", {})
    assert client.notifications[1][0] == "workspace/didChangeConfiguration"
    assert provider.discovered_python_interpreter == workspace_interpreter.resolve()
    assert client.notifications[1][1]["settings"]["python"]["pythonPath"] == str(trusted_interpreter.resolve())
    assert provider.position_encoding == "utf-16"
    assert provider.supports_implementation is True


@pytest.mark.asyncio
async def test_pyright_syncs_full_active_snapshot_before_navigation(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("old_name()\n", encoding="utf-8")
    active = "def new_name():\n    return None\n\nnew_name()\n"
    client = FakeLspClient({"textDocument/definition": None})
    provider = PyrightProvider(tmp_path)

    first = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=7,
        content=active,
        line=4,
        column=2,
    )
    await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=8,
        content=active.replace("new_name", "newer_name"),
        line=4,
        column=2,
    )

    assert first == []
    assert client.notifications[0] == (
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": source.resolve().as_uri(),
                "languageId": "python",
                "version": 7,
                "text": active,
            }
        },
    )
    assert client.notifications[1][0] == "textDocument/didChange"
    assert client.notifications[1][1]["textDocument"]["version"] == 8
    assert client.notifications[1][1]["contentChanges"] == [{"text": active.replace("new_name", "newer_name")}]
    request_method, request_params = client.requests[0]
    assert request_method == "textDocument/definition"
    assert request_params["position"] == {"line": 3, "character": 1}


@pytest.mark.asyncio
async def test_pyright_keeps_lsp_document_versions_monotonic_after_browser_version_reset(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("name()\n", encoding="utf-8")
    client = FakeLspClient({"textDocument/definition": None})
    provider = PyrightProvider(tmp_path)

    await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=9,
        content="first_name()\n",
        line=1,
        column=2,
    )
    await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=1,
        content="second_name()\n",
        line=1,
        column=2,
    )

    assert client.notifications[1][0] == "textDocument/didChange"
    assert client.notifications[1][1]["textDocument"]["version"] == 10


@pytest.mark.asyncio
async def test_pyright_normalizes_location_and_location_link_with_utf16_emoji_prefix(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    target = tmp_path / "target.py"
    source.write_text("target\n", encoding="utf-8")
    target.write_text("😀target = 1\n", encoding="utf-8")
    target_uri = target.resolve().as_uri()
    client = FakeLspClient(
        {
            "textDocument/definition": [
                {
                    "uri": target_uri,
                    "range": {
                        "start": {"line": 0, "character": 2},
                        "end": {"line": 0, "character": 8},
                    },
                },
                {
                    "targetUri": target_uri,
                    "targetRange": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 12},
                    },
                    "targetSelectionRange": {
                        "start": {"line": 0, "character": 2},
                        "end": {"line": 0, "character": 8},
                    },
                },
            ]
        }
    )
    provider = PyrightProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=1,
        content="😀target\n",
        line=1,
        column=2,
    )

    assert client.requests[0][1]["position"] == {"line": 0, "character": 2}
    assert len(result) == 2
    assert result[0]["provider"] == "pyright"
    assert result[0]["path"] == "target.py"
    assert result[0]["range"]["start"] == {"line": 1, "column": 2}
    assert result[0]["range"]["end"] == {"line": 1, "column": 8}
    assert result[1]["selection_range"] == result[0]["selection_range"]
    assert result[1]["range"]["start"] == {"line": 1, "column": 1}


@pytest.mark.asyncio
async def test_pyright_uses_unsaved_cross_file_snapshot_for_location_ranges(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    target = tmp_path / "target.py"
    source.write_text("renamed\n", encoding="utf-8")
    target.write_text("old_name = 1\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "textDocument/definition": {
                "uri": target.resolve().as_uri(),
                "range": {
                    "start": {"line": 1, "character": 0},
                    "end": {"line": 1, "character": 7},
                },
            }
        }
    )
    provider = PyrightProvider(tmp_path)
    await provider.sync_documents(
        client,
        [LanguageDocument("target.py", "python", 3, "prefix = 0\nrenamed = 1\n")],
    )

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=2,
        content="renamed\n",
        line=1,
        column=2,
    )

    assert result[0]["path"] == "target.py"
    assert result[0]["selection_range"]["start"] == {"line": 2, "column": 1}
    assert [method for method, _params in client.notifications] == [
        "textDocument/didOpen",
        "textDocument/didOpen",
    ]


@pytest.mark.asyncio
async def test_pyright_returns_no_fake_implementation_when_server_does_not_support_it(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("run()\n", encoding="utf-8")
    client = FakeLspClient({"textDocument/implementation": [{"unexpected": True}]})
    provider = PyrightProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="implementation",
        path=source,
        language_id="python",
        version=1,
        content="run()\n",
        line=1,
        column=2,
    )

    assert result == []
    assert client.requests == []


@pytest.mark.asyncio
async def test_pyright_rejects_workspace_external_file_locations_until_external_registry_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "main.py"
    source.write_text("target\n", encoding="utf-8")
    external = tmp_path / "outside.py"
    external.write_text("target = 1\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "textDocument/definition": {
                "uri": external.resolve().as_uri(),
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 6},
                },
            }
        }
    )
    provider = PyrightProvider(workspace)

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=1,
        content="target\n",
        line=1,
        column=2,
    )

    assert result == []


@pytest.mark.asyncio
async def test_pyright_does_not_expose_workspace_venv_dependency_as_editable_source(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    dependency = tmp_path / ".venv" / "Lib" / "site-packages" / "package.py"
    dependency.parent.mkdir(parents=True)
    source.write_text("package.run()\n", encoding="utf-8")
    dependency.write_text("def run():\n    return None\n", encoding="utf-8")
    client = FakeLspClient(
        {
            "textDocument/definition": {
                "uri": dependency.resolve().as_uri(),
                "range": {
                    "start": {"line": 0, "character": 4},
                    "end": {"line": 0, "character": 7},
                },
            }
        }
    )
    provider = PyrightProvider(tmp_path)

    result = await provider.navigate(
        client,
        kind="definition",
        path=source,
        language_id="python",
        version=1,
        content="package.run()\n",
        line=1,
        column=10,
    )

    assert result == []


@pytest.mark.asyncio
async def test_pyright_serializes_snapshot_sync_with_its_navigation_request(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("name()\n", encoding="utf-8")
    first_request_started = asyncio.Event()
    release_first = asyncio.Event()

    class BlockingClient(FakeLspClient):
        async def request(self, method: str, params: dict[str, Any]) -> Any:
            self.requests.append((method, params))
            if method == "textDocument/definition" and len(self.requests) == 1:
                first_request_started.set()
                await release_first.wait()
            return None

    client = BlockingClient()
    provider = PyrightProvider(tmp_path)
    first = asyncio.create_task(
        provider.navigate(
            client,
            kind="definition",
            path=source,
            language_id="python",
            version=1,
            content="first_name()\n",
            line=1,
            column=2,
        )
    )
    await first_request_started.wait()
    second = asyncio.create_task(
        provider.navigate(
            client,
            kind="definition",
            path=source,
            language_id="python",
            version=2,
            content="second_name()\n",
            line=1,
            column=2,
        )
    )
    await asyncio.sleep(0)

    assert [method for method, _params in client.notifications] == ["textDocument/didOpen"]
    release_first.set()
    await asyncio.gather(first, second)
    assert [method for method, _params in client.notifications] == [
        "textDocument/didOpen",
        "textDocument/didChange",
    ]
