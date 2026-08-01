from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot.web.server as server_module


def test_public_host_info_recognizes_windows_11_when_python_reports_release_10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(server_module.platform, "release", lambda: "10")
    monkeypatch.setattr(
        server_module.sys,
        "getwindowsversion",
        lambda: SimpleNamespace(build=22631, product_type=1),
        raising=False,
    )
    monkeypatch.setattr(server_module, "_get_total_memory_bytes", lambda: None)

    host_info = server_module._build_public_host_info()

    assert host_info["operating_system"] == "Windows 11"
