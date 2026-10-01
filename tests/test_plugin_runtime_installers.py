from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request

import pytest

from bot.plugins.execution import normalize_action_result
from bot.plugins.runtime_installers import (
    GRAPHVIZ_RUNTIME_KEY,
    PluginRuntimeInstaller,
    RuntimeInstallSpec,
    RuntimeInstallerError,
    _HttpsOnlyRedirectHandler,
    _safe_extract,
    _target_path,
    _runtime_install_lock,
)


class _Response:
    def __init__(self, data: bytes, *, content_length: int | None = None):
        self._stream = io.BytesIO(data)
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return "https://example.test/runtime.zip"

    def read(self, size: int):
        return self._stream.read(size)


def _spec(data: bytes, *, max_download_bytes: int = 1024 * 1024, sha256: str | None = None) -> RuntimeInstallSpec:
    return RuntimeInstallSpec(
        key=GRAPHVIZ_RUNTIME_KEY,
        plugin_id="mermaid-visio",
        version="test",
        url="https://example.test/runtime.zip",
        sha256=sha256 or hashlib.sha256(data).hexdigest(),
        max_download_bytes=max_download_bytes,
        target_relative_path="vendor/graphviz/win-x64",
    )


def _archive(
    *,
    member_name: str = "Graphviz/bin/dot.exe",
    content: bytes = b"new",
    members: list[tuple[str, bytes]] | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, item in members or [(member_name, content)]:
            archive.writestr(name, item)
    return output.getvalue()


def _installer(data: bytes, spec: RuntimeInstallSpec, *, content_length: int | None = None) -> PluginRuntimeInstaller:
    return PluginRuntimeInstaller(
        {GRAPHVIZ_RUNTIME_KEY: spec},
        opener=lambda _url, timeout: _Response(data, content_length=content_length),
    )


def test_bad_sha256_does_not_write_runtime(tmp_path: Path) -> None:
    data = _archive()
    installer = _installer(data, _spec(data, sha256="0" * 64))

    with pytest.raises(RuntimeInstallerError, match="SHA256"):
        installer.install(GRAPHVIZ_RUNTIME_KEY, tmp_path)

    assert not (tmp_path / "vendor").exists()


def test_success_notice_uses_current_graphviz_license(tmp_path: Path) -> None:
    data = _archive()
    installer = _installer(data, _spec(data))

    result = installer.install(GRAPHVIZ_RUNTIME_KEY, tmp_path)

    assert result["ok"] is True
    notice = (tmp_path / "vendor" / "graphviz" / "win-x64" / "MERMAID_VISIO_GRAPHVIZ_NOTICE.txt").read_text(
        encoding="utf-8"
    )
    assert "Eclipse Public License 2.0" in notice
    assert "Common Public License" not in notice


def test_content_length_and_actual_size_are_bounded(tmp_path: Path) -> None:
    data = _archive()
    spec = _spec(data, max_download_bytes=len(data) - 1)
    installer = _installer(data, spec, content_length=len(data))

    with pytest.raises(RuntimeInstallerError, match="大小限制"):
        installer.install(GRAPHVIZ_RUNTIME_KEY, tmp_path)


def test_zip_traversal_is_rejected_and_old_runtime_is_preserved(tmp_path: Path) -> None:
    target = tmp_path / "vendor" / "graphviz" / "win-x64"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "dot.exe").write_bytes(b"old")
    data = _archive(member_name="../outside/dot.exe")
    installer = _installer(data, _spec(data))

    with pytest.raises(RuntimeInstallerError, match="路径"):
        installer.install(GRAPHVIZ_RUNTIME_KEY, tmp_path)

    assert (target / "bin" / "dot.exe").read_bytes() == b"old"
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize(
    "member_name",
    [
        "Graphviz/bin/dot.exe:Zone.Identifier",
        "Graphviz/bin/CON.txt",
        "Graphviz/bin/com1.dll",
        "Graphviz/bin/report. ",
        "Graphviz/bin/report ",
        "Graphviz/bin/report?draft",
    ],
)
def test_windows_unsafe_zip_member_names_are_rejected(tmp_path: Path, member_name: str) -> None:
    data = _archive(member_name=member_name)
    installer = _installer(data, _spec(data))

    with pytest.raises(RuntimeInstallerError, match="Windows"):
        installer.install(GRAPHVIZ_RUNTIME_KEY, tmp_path)


def test_case_insensitive_duplicate_zip_members_are_rejected(tmp_path: Path) -> None:
    data = _archive(
        members=[
            ("Graphviz/bin/dot.exe", b"one"),
            ("Graphviz/bin/DOT.EXE", b"two"),
        ]
    )
    installer = _installer(data, _spec(data))

    with pytest.raises(RuntimeInstallerError, match="重复成员"):
        installer.install(GRAPHVIZ_RUNTIME_KEY, tmp_path)


def test_extraction_enforces_actual_streamed_member_size(tmp_path: Path) -> None:
    member = zipfile.ZipInfo("Graphviz/bin/dot.exe")
    member.file_size = 1

    class _Archive:
        def infolist(self):
            return [member]

        def open(self, _member, _mode):
            return io.BytesIO(b"too-large")

    with pytest.raises(RuntimeInstallerError, match="大小限制"):
        _safe_extract(_Archive(), tmp_path / "extract", max_bytes=1)


@pytest.mark.parametrize("link_path", ["vendor", "vendor/graphviz/win-x64"])
def test_target_policy_rejects_lexical_symlinks(tmp_path: Path, link_path: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / link_path
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(RuntimeInstallerError, match="符号链接"):
        _target_path(tmp_path, _spec(_archive()))


def test_https_redirect_handler_rejects_downgrade() -> None:
    handler = _HttpsOnlyRedirectHandler()

    with pytest.raises(RuntimeInstallerError, match="HTTPS"):
        handler.redirect_request(Request("https://example.test/runtime.zip"), object(), 302, "Found", {}, "http://example.test/runtime.zip")


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_chain_rejects_insecure_intermediate_hop(status: int) -> None:
    handler = _HttpsOnlyRedirectHandler()
    request = Request("https://example.test/start")
    next_request = handler.redirect_request(
        request,
        object(),
        status,
        "Redirect",
        {},
        "https://example.test/next",
    )
    assert next_request is not None

    with pytest.raises(RuntimeInstallerError, match="HTTPS"):
        handler.redirect_request(
            next_request,
            object(),
            status,
            "Redirect",
            {},
            "http://example.test/insecure",
        )


def test_download_elapsed_timeout_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _archive()
    installer = _installer(data, _spec(data), content_length=len(data))
    ticks = iter([0.0, 0.0, 0.0, 1.0])
    monkeypatch.setattr("bot.plugins.runtime_installers.time.monotonic", lambda: next(ticks))
    installer.timeout_seconds = 0.5

    with pytest.raises(RuntimeInstallerError, match="超时"):
        installer._download(_spec(data), tmp_path / "runtime.zip")


def test_replacement_failure_restores_old_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "vendor" / "graphviz" / "win-x64"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "dot.exe").write_bytes(b"old")
    data = _archive(content=b"new")
    installer = _installer(data, _spec(data))
    original_rename = Path.rename

    def fail_promotion(source: Path, destination: Path):
        if source.name.startswith(".win-x64.staging-") and Path(destination).name == "win-x64":
            raise OSError("promotion failed")
        return original_rename(source, destination)

    monkeypatch.setattr(Path, "rename", fail_promotion)
    with pytest.raises(RuntimeInstallerError, match="promotion failed"):
        installer.install(GRAPHVIZ_RUNTIME_KEY, tmp_path)

    assert (target / "bin" / "dot.exe").read_bytes() == b"old"


def test_duplicate_runtime_installs_share_one_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _archive()
    spec = _spec(data)
    installer = _installer(data, spec)
    first_entered = threading.Event()
    second_waiting = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()

    def observed_lock(key):
        lock = _runtime_install_lock(key)
        if first_entered.is_set():
            second_waiting.set()
        return lock

    def fake_install(_spec, _target):
        if not first_entered.is_set():
            first_entered.set()
            assert release_first.wait(2)
        else:
            second_entered.set()
        return {"ok": True}

    monkeypatch.setattr(installer, "_install_locked", fake_install)
    monkeypatch.setattr("bot.plugins.runtime_installers._runtime_install_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(installer.install, GRAPHVIZ_RUNTIME_KEY, tmp_path)
        assert first_entered.wait(2)
        second = pool.submit(installer.install, GRAPHVIZ_RUNTIME_KEY, tmp_path)
        try:
            assert second_waiting.wait(2)
            assert not second_entered.wait(0.1)
        finally:
            release_first.set()
        assert first.result() == {"ok": True}
        assert second.result() == {"ok": True}

    assert second_entered.is_set()
    assert _runtime_install_lock("same") is _runtime_install_lock("same")


def test_plugin_graphviz_code_has_no_download_implementation() -> None:
    path = Path(__file__).parents[1] / "examples" / "plugins" / "mermaid-visio" / "backend" / "mermaid_visio" / "graphviz_runtime.py"
    source = path.read_text(encoding="utf-8")
    assert "urllib.request" not in source
    assert "urlretrieve" not in source
    assert "extractall" not in source


def test_plugin_cannot_attach_runtime_parameters_to_host_effect() -> None:
    with pytest.raises(RuntimeError, match="不接受插件提供"):
        normalize_action_result(
            {"hostEffects": [{"type": "install_plugin_runtime", "url": "https://attacker.test/runtime.zip"}]}
        )
