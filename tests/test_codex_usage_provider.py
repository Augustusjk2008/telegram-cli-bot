from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path

import pytest


def _provider_module():
    try:
        return importlib.import_module("bot.codex_usage.provider")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Codex usage provider 核心包尚未实现: {exc}")


def _write_root_config(codex_home: Path, content: str) -> Path:
    codex_home.mkdir(parents=True, exist_ok=True)
    path = codex_home / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def _resolve(
    tmp_path: Path,
    content: str | None,
    *,
    argv: tuple[str, ...] = (),
):
    provider = _provider_module()
    codex_home = tmp_path / "codex-home"
    if content is not None:
        _write_root_config(codex_home, content)
    resolver = provider.CodexProviderResolver()
    return resolver.resolve(env={"CODEX_HOME": str(codex_home)}, argv=argv)


def test_root_config_path_uses_codex_home_or_home_dot_codex(tmp_path: Path) -> None:
    provider = _provider_module()

    assert provider.get_root_config_path(
        {"CODEX_HOME": str(tmp_path / "custom-home")},
        home_dir=tmp_path / "fallback-home",
    ) == tmp_path / "custom-home" / "config.toml"
    assert provider.get_root_config_path(
        {"CODEX_HOME": "   "},
        home_dir=tmp_path / "fallback-home",
    ) == tmp_path / "fallback-home" / ".codex" / "config.toml"


def test_missing_root_config_resolves_to_openai_official(tmp_path: Path) -> None:
    result = _resolve(tmp_path, None)

    assert result.key == "openai_official"
    assert result.kind == "openai_official"
    assert result.base_url is None
    assert result.resolution == "config_missing"


def test_openai_custom_base_url_is_normalized_and_hashed(tmp_path: Path) -> None:
    result = _resolve(
        tmp_path,
        'openai_base_url = " HTTPS://Example.COM:443/V1/ "\n',
    )
    expected_url = "https://example.com/V1"

    assert result.kind == "base_url"
    assert result.base_url == expected_url
    assert result.key == f"base_url_sha256:{hashlib.sha256(expected_url.encode()).hexdigest()}"
    assert result.resolution == "resolved"


def test_custom_provider_ids_with_same_normalized_url_share_stable_key(tmp_path: Path) -> None:
    first = _resolve(
        tmp_path / "first",
        '''
model_provider = "first"
[model_providers.first]
base_url = "https://Provider.EXAMPLE/v1/"
''',
    )
    second = _resolve(
        tmp_path / "second",
        '''
model_provider = "second"
[model_providers.second]
base_url = "https://provider.example/v1"
''',
    )

    assert first.kind == second.kind == "base_url"
    assert first.base_url == second.base_url == "https://provider.example/v1"
    assert first.key == second.key


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("http://EXAMPLE.com:80/Path/", "http://example.com/Path"),
        ("https://EXAMPLE.com:443/Path/", "https://example.com/Path"),
        ("https://EXAMPLE.com:8443/Path/", "https://example.com:8443/Path"),
        ("https://EXAMPLE.com/CaseSensitive/", "https://example.com/CaseSensitive"),
    ],
)
def test_normalize_base_url_cleans_only_safe_equivalent_parts(raw_url: str, expected: str) -> None:
    provider = _provider_module()

    assert provider.normalize_base_url(raw_url) == expected


@pytest.mark.parametrize(
    "raw_url",
    [
        "ftp://provider.example/v1",
        "https:///missing-host",
        "https://user:secret@provider.example/v1",
        "https://provider.example/v1?token=secret",
        "https://provider.example/v1#fragment",
        "https://provider.example:invalid/v1",
    ],
)
def test_normalize_base_url_rejects_unsafe_or_invalid_urls(raw_url: str) -> None:
    provider = _provider_module()

    assert provider.normalize_base_url(raw_url) is None


def test_empty_final_base_url_stays_openai_official(tmp_path: Path) -> None:
    result = _resolve(tmp_path, 'model_provider = "openai"\nopenai_base_url = "  "\n')

    assert result.key == "openai_official"
    assert result.kind == "openai_official"
    assert result.resolution == "resolved"


@pytest.mark.parametrize(
    ("content", "resolution"),
    [
        ('model_provider = "missing"\n', "provider_missing"),
        ('openai_base_url = "mailto:not-a-provider"\n', "invalid_base_url"),
        ('model_provider = [\n', "config_invalid"),
    ],
)
def test_unresolvable_root_config_is_recorded_as_unknown(
    tmp_path: Path,
    content: str,
    resolution: str,
) -> None:
    result = _resolve(tmp_path, content)

    assert result.key == "unknown"
    assert result.kind == "unknown"
    assert result.base_url is None
    assert result.resolution == resolution


@pytest.mark.parametrize(
    "argv",
    [
        ("--profile", "work"),
        ("--profile=work",),
        ("-p", "work"),
        ("-pwork",),
        ("--oss",),
        ("-c", 'model_provider = "other"'),
        ("--config", 'openai_base_url = "https://other.example"'),
        ("--config=model_providers.other.base_url = \"https://other.example\"",),
        ("-c", 'model_providers.proxy = { base_url = "https://other.example" }'),
        ("--config", 'model_providers."proxy.acme".base_url = "https://other.example"'),
    ],
)
def test_provider_affecting_command_overrides_resolve_to_unknown(
    tmp_path: Path,
    argv: tuple[str, ...],
) -> None:
    result = _resolve(tmp_path, 'openai_base_url = "https://provider.example/v1"\n', argv=argv)

    assert result.key == "unknown"
    assert result.kind == "unknown"
    assert result.resolution == "unsupported_override"


def test_unrelated_config_overrides_do_not_hide_provider_attribution(tmp_path: Path) -> None:
    result = _resolve(
        tmp_path,
        'openai_base_url = "https://provider.example/v1"\n',
        argv=(
            "-c",
            'model_reasoning_effort = "high"',
            "--config",
            'trust_level = "trusted"',
        ),
    )

    assert result.kind == "base_url"
    assert result.base_url == "https://provider.example/v1"


def test_root_config_cache_uses_absolute_path_mtime_and_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_module()
    codex_home = tmp_path / "codex-home"
    config_path = _write_root_config(codex_home, 'openai_base_url = "https://one.example/v1"\n')
    resolver = provider.CodexProviderResolver()
    calls: list[Path] = []
    original_load = provider._load_toml

    def spy_load(path: Path):
        calls.append(path)
        return original_load(path)

    monkeypatch.setattr(provider, "_load_toml", spy_load)

    first = resolver.resolve(env={"CODEX_HOME": str(codex_home)}, argv=())
    second = resolver.resolve(env={"CODEX_HOME": str(codex_home)}, argv=())
    config_path.write_text('openai_base_url = "https://two.example/longer-path"\n', encoding="utf-8")
    third = resolver.resolve(env={"CODEX_HOME": str(codex_home)}, argv=())

    assert first.base_url == second.base_url == "https://one.example/v1"
    assert third.base_url == "https://two.example/longer-path"
    assert calls == [config_path.resolve(), config_path.resolve()]


def test_environment_base_url_is_not_an_attribution_source(tmp_path: Path) -> None:
    provider = _provider_module()
    resolver = provider.CodexProviderResolver()

    result = resolver.resolve(
        env={
            "CODEX_HOME": str(tmp_path / "missing-home"),
            "OPENAI_BASE_URL": "https://must-not-be-read.example",
        },
        argv=(),
    )

    assert result.key == "openai_official"
    assert result.base_url is None


def test_custom_provider_without_a_final_base_url_is_unknown(tmp_path: Path) -> None:
    result = _resolve(
        tmp_path,
        '''
model_provider = "proxy"
[model_providers.proxy]
name = "Only a display name"
''',
    )

    assert result.key == "unknown"
    assert result.kind == "unknown"
    assert result.resolution == "provider_missing"


def test_root_config_ignores_profile_config_files(tmp_path: Path) -> None:
    provider = _provider_module()
    codex_home = tmp_path / "codex-home"
    _write_root_config(codex_home, 'openai_base_url = "https://root.example/v1"\n')
    (codex_home / "work.config.toml").write_text(
        'openai_base_url = "https://profile.example/v1"\n',
        encoding="utf-8",
    )

    result = provider.CodexProviderResolver().resolve(
        env={"CODEX_HOME": str(codex_home)},
        argv=(),
    )

    assert result.base_url == "https://root.example/v1"


def test_different_paths_and_non_default_ports_keep_distinct_provider_keys() -> None:
    provider = _provider_module()
    path_one = provider.normalize_base_url("https://provider.example/v1")
    path_two = provider.normalize_base_url("https://provider.example/v2")
    port = provider.normalize_base_url("https://provider.example:8443/v1")

    assert path_one and path_two and port
    assert len(
        {
            provider.stable_provider_key(path_one),
            provider.stable_provider_key(path_two),
            provider.stable_provider_key(port),
        }
    ) == 3


def test_cache_invalidates_when_only_mtime_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_module()
    codex_home = tmp_path / "codex-home"
    config_path = _write_root_config(codex_home, 'openai_base_url = "https://one.example/v1"\n')
    resolver = provider.CodexProviderResolver()
    calls: list[Path] = []
    original_load = provider._load_toml

    def spy_load(path: Path):
        calls.append(path)
        return original_load(path)

    monkeypatch.setattr(provider, "_load_toml", spy_load)
    first = resolver.resolve(env={"CODEX_HOME": str(codex_home)}, argv=())
    before = config_path.stat()
    config_path.write_text('openai_base_url = "https://two.example/v1"\n', encoding="utf-8")
    assert config_path.stat().st_size == before.st_size
    os.utime(config_path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    second = resolver.resolve(env={"CODEX_HOME": str(codex_home)}, argv=())

    assert first.base_url == "https://one.example/v1"
    assert second.base_url == "https://two.example/v1"
    assert calls == [config_path.resolve(), config_path.resolve()]


@pytest.mark.parametrize(
    "argv",
    [
        ("-cmodel_providers.proxy.base_url = \"https://other.example\"",),
        ("--config=model_provider = \"other\"",),
    ],
)
def test_attached_provider_override_forms_are_unknown(tmp_path: Path, argv: tuple[str, ...]) -> None:
    result = _resolve(tmp_path, 'openai_base_url = "https://provider.example/v1"\n', argv=argv)

    assert result.key == "unknown"
    assert result.resolution == "unsupported_override"


def test_similarly_named_or_unrelated_config_keys_do_not_trigger_unknown(tmp_path: Path) -> None:
    result = _resolve(
        tmp_path,
        'openai_base_url = "https://provider.example/v1"\n',
        argv=(
            "-c",
            'model_providerx = "other"',
            "--config",
            'model_providers.proxy.name = "display"',
        ),
    )

    assert result.base_url == "https://provider.example/v1"
