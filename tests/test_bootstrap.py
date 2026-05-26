import sys
from types import SimpleNamespace

from bot.bootstrap import ensure_nofile_limit


def test_ensure_nofile_limit_raises_soft_limit(monkeypatch):
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = SimpleNamespace(
        RLIMIT_NOFILE=1,
        RLIM_INFINITY=-1,
        getrlimit=lambda _: (256, 4096),
        setrlimit=lambda key, value: calls.append((key, value)),
    )
    monkeypatch.setitem(sys.modules, "resource", fake_resource)

    ensure_nofile_limit(2048)

    assert calls == [(1, (2048, 4096))]


def test_ensure_nofile_limit_skips_when_soft_limit_is_already_high(monkeypatch):
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = SimpleNamespace(
        RLIMIT_NOFILE=1,
        RLIM_INFINITY=-1,
        getrlimit=lambda _: (8192, 8192),
        setrlimit=lambda key, value: calls.append((key, value)),
    )
    monkeypatch.setitem(sys.modules, "resource", fake_resource)

    ensure_nofile_limit(2048)

    assert calls == []
