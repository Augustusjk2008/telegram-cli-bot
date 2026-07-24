from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.language_server.external_source_registry import (
    ApprovedRoot,
    ExternalSourceError,
    ExternalSourceNotFoundError,
    ExternalSourcePolicyError,
    ExternalSourceRegistry,
    ExternalSourceTextError,
    ExternalSourceTooLargeError,
    ExternalSourceUriError,
)
from bot.language_server.manager import LanguageServerRuntime, LanguageServerRuntimeKey
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_READ_FILE_CONTENT
from bot.web.server import WebApiServer


class DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }


def _scope(root: Path, *, alias: str = "main", user_id: int = 7, provider: str = "pyright") -> dict[str, object]:
    return {
        "alias": alias,
        "user_id": user_id,
        "workspace_root": root,
        "provider_id": provider,
    }


def test_registry_canonicalizes_uri_and_redacts_absolute_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    dependency_root = tmp_path / "python" / "site-packages"
    workspace.mkdir()
    dependency_root.mkdir(parents=True)
    target = dependency_root / "demo.py"
    target.write_text("# coding: utf-8\nvalue = 1\n", encoding="utf-8")

    registry = ExternalSourceRegistry(enabled=True)
    record = registry.register(
        uri=target.as_uri(),
        approved_roots=[ApprovedRoot(dependency_root, "python-site-packages")],
        **_scope(workspace),
    )

    assert record.source_id.startswith("src_")
    assert str(target) not in record.display_path
    assert record.display_path == "python-site-packages/demo.py"
    data = registry.read(record.source_id, **_scope(workspace))
    assert data["content"] == target.read_bytes().decode("utf-8")
    assert data["path"] == record.display_path
    assert data["read_only"] is True


def test_registry_binds_alias_user_workspace_and_provider(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    dependency = tmp_path / "dep"
    workspace.mkdir()
    dependency.mkdir()
    target = dependency / "lib.py"
    target.write_text("pass\n", encoding="utf-8")
    registry = ExternalSourceRegistry(enabled=True)
    record = registry.register(
        target,
        approved_roots=[dependency],
        **_scope(workspace, alias="alpha", user_id=11, provider="typescript"),
    )

    with pytest.raises(ExternalSourceNotFoundError):
        registry.resolve(record.source_id, **_scope(workspace, alias="beta", user_id=11, provider="typescript"))
    with pytest.raises(ExternalSourceNotFoundError):
        registry.resolve(record.source_id, **_scope(workspace, alias="alpha", user_id=12, provider="typescript"))
    with pytest.raises(ExternalSourceNotFoundError):
        registry.resolve(record.source_id, **_scope(workspace, alias="alpha", user_id=11, provider="pyright"))
    other_workspace = tmp_path / "other-workspace"
    other_workspace.mkdir()
    with pytest.raises(ExternalSourceNotFoundError):
        registry.resolve(record.source_id, **_scope(other_workspace, alias="alpha", user_id=11, provider="typescript"))
    with pytest.raises(ExternalSourceNotFoundError):
        registry.resolve("src_forged-token", **_scope(workspace, alias="alpha", user_id=11, provider="typescript"))


def test_registry_ttl_and_per_user_lru(tmp_path: Path) -> None:
    now = [100.0]
    registry = ExternalSourceRegistry(enabled=True, ttl_seconds=10, max_per_user=2, clock=lambda: now[0])
    workspace = tmp_path / "workspace"
    root = tmp_path / "dependency"
    workspace.mkdir()
    root.mkdir()
    target = root / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")
    scope = _scope(workspace)
    first = registry.register(target, approved_roots=[root], **scope)
    now[0] += 1
    second = registry.register(target, approved_roots=[root], **scope)
    now[0] += 1
    third = registry.register(target, approved_roots=[root], **scope)
    with pytest.raises(ExternalSourceNotFoundError):
        registry.resolve(first.source_id, **scope)
    assert registry.resolve(second.source_id, **scope).source_id == second.source_id
    assert registry.resolve(third.source_id, **scope).source_id == third.source_id
    now[0] += 10
    with pytest.raises(ExternalSourceNotFoundError):
        registry.resolve(second.source_id, **scope)


def test_registry_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    workspace.mkdir()
    approved.mkdir()
    outside.mkdir()
    external = outside / "secret.py"
    external.write_text("secret\n", encoding="utf-8")
    link = approved / "link.py"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    registry = ExternalSourceRegistry(enabled=True)
    with pytest.raises(ExternalSourcePolicyError):
        registry.register(link, approved_roots=[approved], **_scope(workspace))


@pytest.mark.parametrize("replacement", ["symlink", "hardlink"])
def test_registry_read_rejects_target_replaced_after_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replacement: str,
) -> None:
    workspace = tmp_path / "workspace"
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    workspace.mkdir()
    approved.mkdir()
    outside.mkdir()
    target = approved / "module.py"
    target.write_text("answer = 42\n", encoding="utf-8")
    secret_text = "TOP-SECRET-outside-content"
    secret = outside / "secret.py"
    secret.write_text(secret_text, encoding="utf-8")
    registry = ExternalSourceRegistry(enabled=True)
    scope = _scope(workspace)
    record = registry.register(target, approved_roots=[approved], **scope)

    original_resolve = registry.resolve
    swapped = False

    def resolve_then_replace(*args: object, **kwargs: object):
        nonlocal swapped
        resolved = original_resolve(*args, **kwargs)
        if not swapped:
            swapped = True
            target.unlink()
            try:
                if replacement == "symlink":
                    target.symlink_to(secret)
                else:
                    os.link(secret, target)
            except (OSError, NotImplementedError) as exc:
                pytest.skip(f"当前环境不支持 {replacement} 替换: {exc}")
        return resolved

    monkeypatch.setattr(registry, "resolve", resolve_then_replace)

    with pytest.raises(ExternalSourcePolicyError) as error:
        registry.read(record.source_id, **scope)

    assert secret_text not in str(error.value)


def test_registry_concurrent_register_never_exceeds_per_user_capacity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    approved = tmp_path / "approved"
    workspace.mkdir()
    approved.mkdir()
    target = approved / "module.py"
    target.write_text("answer = 42\n", encoding="utf-8")
    registry = ExternalSourceRegistry(enabled=True, max_per_user=1)
    scope = _scope(workspace)
    release_barrier = threading.Barrier(2, timeout=5)
    original_lock = registry._lock

    class SynchronizingLock:
        def __init__(self) -> None:
            self._released = 0
            self._released_lock = threading.Lock()

        def __enter__(self) -> "SynchronizingLock":
            original_lock.acquire()
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
            original_lock.release()
            with self._released_lock:
                self._released += 1
                synchronize = self._released <= 2
            if synchronize:
                release_barrier.wait()
            return False

    monkeypatch.setattr(registry, "_lock", SynchronizingLock())
    errors: list[BaseException] = []

    def register() -> None:
        try:
            registry.register(target, approved_roots=[approved], **scope)
        except BaseException as exc:  # pragma: no cover - assertion below reports worker errors
            errors.append(exc)

    workers = [threading.Thread(target=register) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
    finally:
        registry._lock = original_lock

    assert not any(worker.is_alive() for worker in workers)
    assert not errors
    assert sum(record.user_id == int(scope["user_id"]) for record in registry.snapshot()) <= 1


def test_registry_rejects_unsupported_uri_binary_and_large_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    approved = tmp_path / "approved"
    workspace.mkdir()
    approved.mkdir()
    registry = ExternalSourceRegistry(enabled=True)
    with pytest.raises(ExternalSourceUriError):
        registry.register("untitled:buffer-1", approved_roots=[approved], **_scope(workspace))

    binary = approved / "binary.py"
    binary.write_bytes(b"\x00\x01\x02")
    binary_record = registry.register(binary, approved_roots=[approved], **_scope(workspace))
    with pytest.raises(ExternalSourceTextError):
        registry.read(binary_record.source_id, **_scope(workspace))

    large = approved / "large.py"
    large.write_text("x" * 32, encoding="utf-8")
    small_registry = ExternalSourceRegistry(enabled=True, max_source_bytes=8)
    large_record = small_registry.register(large, approved_roots=[approved], **_scope(workspace))
    with pytest.raises(ExternalSourceTooLargeError):
        small_registry.read(large_record.source_id, **_scope(workspace))


def test_runtime_injects_registry_and_scope_into_provider(tmp_path: Path) -> None:
    registry = ExternalSourceRegistry(enabled=True)
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 7, tmp_path.resolve(), "pyright"),
        ("pyright-langserver", "--stdio"),
        request_timeout=1,
        external_source_registry=registry,
    )

    assert runtime.provider.external_source_registry is registry
    assert runtime.provider.external_source_alias == "main"
    assert runtime.provider.external_source_user_id == 7


def _build_server(
    tmp_path: Path,
    registry: ExternalSourceRegistry | None,
    monkeypatch: pytest.MonkeyPatch,
    *,
    language_server_manager: object | None = None,
) -> WebApiServer:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(
            alias="main",
            token="main_tok",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
        ),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    options: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 8765,
        "tunnel_service": DummyTunnelService(),
    }
    if registry is not None:
        options["external_source_registry"] = registry
    if language_server_manager is not None:
        options["language_server_manager"] = language_server_manager
    server = WebApiServer(
        manager,
        **options,
    )
    return server


def _auth(*capabilities: str, user_id: int = 7) -> AuthContext:
    return AuthContext(
        user_id=user_id,
        token_used=True,
        account_id="member-1",
        username="alice",
        capabilities=set(capabilities),
        is_local_admin=True,
    )


@pytest.mark.asyncio
async def test_external_source_read_routes_require_capability_and_never_accept_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "dependency"
    dependency.mkdir()
    target = dependency / "module.py"
    target.write_bytes(b"answer = 42\r\nsecond = 7\r\n")
    registry = ExternalSourceRegistry(enabled=True)
    server = _build_server(tmp_path, registry, monkeypatch)
    auth = _auth(CAP_READ_FILE_CONTENT)
    monkeypatch.setattr(server, "_auth_context", lambda _request: auth)
    monkeypatch.setattr(server, "_chat_user_id", lambda context: context.user_id)
    assert Path(server._workspace_file_root("main", auth)).resolve() == tmp_path.resolve()
    record = registry.register(
        target,
        approved_roots=[dependency],
        **_scope(tmp_path, user_id=auth.user_id),
    )
    assert registry.resolve(record.source_id, alias="main", user_id=auth.user_id, workspace_root=tmp_path)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            allowed = await client.get(f"/api/bots/main/workspace/external-sources/{record.source_id}")
            allowed_payload = await allowed.json()
            wrong_provider = await client.get(
                f"/api/bots/main/workspace/external-sources/{record.source_id}?provider=typescript"
            )
            wrong_provider_payload = await wrong_provider.json()
            foreign_auth = _auth(CAP_READ_FILE_CONTENT, user_id=auth.user_id + 1)
            monkeypatch.setattr(server, "_auth_context", lambda _request: foreign_auth)
            foreign = await client.get(f"/api/bots/main/workspace/external-sources/{record.source_id}")
            foreign_payload = await foreign.json()
            absolute = await client.get(
                "/api/bots/main/files/read",
                params={"source_id": str(target)},
            )
            absolute_payload = await absolute.json()
            forbidden_auth = _auth(user_id=auth.user_id)
            monkeypatch.setattr(server, "_auth_context", lambda _request: forbidden_auth)
            forbidden = await client.get(f"/api/bots/main/files/read-external?source_id={record.source_id}")
            forbidden_payload = await forbidden.json()
    assert allowed.status == 200, allowed_payload
    assert allowed_payload["data"]["content"] == target.read_bytes().decode("utf-8")
    assert isinstance(allowed_payload["data"]["last_modified_ns"], str)
    assert str(target) not in json.dumps(allowed_payload, ensure_ascii=False)
    assert absolute.status == 400, absolute_payload
    assert absolute_payload["error"]["code"] == "external_source_absolute_path"
    assert wrong_provider.status == 404, wrong_provider_payload
    assert wrong_provider_payload["error"]["code"] == "external_source_not_found"
    assert foreign.status == 404, foreign_payload
    assert foreign_payload["error"]["code"] == "external_source_not_found"
    assert forbidden.status == 403, forbidden_payload


def test_web_server_reuses_injected_runtime_manager_source_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ExternalSourceRegistry(enabled=True)

    class RegistryAwareRuntimeManager:
        external_source_registry = registry

        def diagnostics(self) -> dict[str, object]:
            return {"runtime_count": 0}

    runtime_manager = RegistryAwareRuntimeManager()
    server = _build_server(
        tmp_path,
        None,
        monkeypatch,
        language_server_manager=runtime_manager,
    )

    assert server.external_source_registry is registry
    assert runtime_manager.external_source_registry is registry
