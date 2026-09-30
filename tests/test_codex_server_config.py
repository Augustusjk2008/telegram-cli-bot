import json

import pytest

from bot import app_settings, config
from bot.cli_params import (
    CliParamsConfig,
    clamp_unsafe_cli_params,
    get_default_params,
    get_params_schema,
    with_global_extra_args,
)
from bot.models import BotProfile, GitCommitMessageCliConfig
from bot.profile_store import (
    apply_persisted_main_profile,
    load_managed_profiles,
    persist_main_profile,
    save_managed_profiles,
)


def test_codex_server_defaults_schema_and_parameters_are_independent(monkeypatch):
    monkeypatch.setattr(config, "CLI_MODEL_OPTIONS", ["test-model", "none"])
    params = CliParamsConfig.from_dict({"codex": {"model": "exec-model", "extra_args": ["--search"]}})
    assert get_default_params("codex_server") == get_default_params("codex")
    assert params.codex_server["model"] == "test-model"
    schema = get_params_schema("codex_server")
    assert schema == get_params_schema("codex")
    schema["reasoning_effort"]["enum"].clear()
    assert get_params_schema("codex")["reasoning_effort"]["enum"]

    params.codex_server["extra_args"].append("--server-option")
    params.set_param("codex_server", "model", "server-model")
    restored = CliParamsConfig.from_dict(params.to_dict())
    assert restored.codex["model"] == "exec-model"
    assert restored.codex["extra_args"] == ["--search"]
    assert restored.codex_server["model"] == "server-model"
    restored.reset_to_default("codex_server")
    assert restored.codex_server == get_default_params("codex_server")
    assert restored.codex == params.codex
    restored.reset_to_default()
    assert restored.codex_server == restored.codex


@pytest.mark.parametrize("cli_type", ["codex", "codex_server"])
@pytest.mark.parametrize("unsafe_args", [
    ["--dangerously-bypass-approvals-and-sandbox", "--yolo", "--full-auto",
     "-s", "danger-full-access", "--sandbox", "workspace-write",
     "-a", "never", "--ask-for-approval", "never", "--approval-policy", "never",
     "--add-dir", "C:/outside", "-c", "model=other", "--config", "features.shell_tool=true"],
    ["--dangerously-bypass-approvals-and-sandbox=false", "--yolo=false", "--full-auto=false",
     "-s=danger-full-access", "--sandbox=workspace-write", "-a=never",
     "--ask-for-approval=never", "--approval-policy=never", "--add-dir=C:/outside",
     "-c=model=other", "--config=features.shell_tool=true"],
    ["-sdanger-full-access", "-anever", "-cmodel=other"],
], ids=["separate", "equals", "short-attached"])
def test_codex_family_global_args_obey_permission_filter(cli_type, unsafe_args):
    safe_args = ["--model", "safe-model", "--search", "--color=never"]
    args = [*unsafe_args, *safe_args]
    global_args = config._parse_cli_global_extra_args(json.dumps({cli_type: args}))
    original = CliParamsConfig.from_dict({cli_type: {"yolo": True}})
    merged = with_global_extra_args(original, global_args)
    assert original.get_param(cli_type, "extra_args") == []
    assert merged.get_param(cli_type, "extra_args") == args
    assert clamp_unsafe_cli_params(merged, allow_unsafe_cli=True).to_dict() == merged.to_dict()
    safe = clamp_unsafe_cli_params(merged, allow_unsafe_cli=False)
    assert safe.get_param(cli_type, "extra_args") == safe_args
    assert safe.get_param(cli_type, "yolo") is False
    other = "codex" if cli_type == "codex_server" else "codex_server"
    assert merged.get_param(other, "extra_args") == []


def test_env_service_accepts_codex_server(tmp_path):
    from bot.web.env_service import EnvConfigService

    service = EnvConfigService(tmp_path)
    field = next(item for item in service.snapshot()["items"] if item["key"] == "CLI_TYPE")
    assert "codex_server" in field["options"]
    result = service.reload_preview({"values": {"CLI_TYPE": "codex_server", "CLI_PATH": "codex"}})
    assert "CLI_TYPE" in result["changedKeys"]


@pytest.mark.parametrize("path", [None, "C:/tools/codex.cmd"])
def test_codex_server_profile_and_git_config_round_trip(tmp_path, monkeypatch, path):
    monkeypatch.setattr(config, "CLI_TYPE", "claude")
    monkeypatch.setattr(config, "CLI_PATH", "C:/tools/claude.cmd")
    data = {"alias": "server", "cli_type": "codex_server", "cli_path": path,
            "cli_params": {"codex_server": {"model": "server-model"}, "codex": {"model": "exec-model"}}}
    profile = BotProfile.from_dict(data)
    assert profile.cli_path == (path or "codex")
    assert profile.supported_execution_modes == ["cli"]
    assert profile.default_execution_mode == "cli"
    managed_file = tmp_path / "managed.json"
    save_managed_profiles(managed_file, {profile.alias: profile})
    restored = load_managed_profiles(managed_file)[profile.alias]
    assert restored.cli_type == "codex_server"
    assert restored.cli_params.to_dict() == profile.cli_params.to_dict()
    assert restored.cli_path == profile.cli_path

    settings_file = tmp_path / "app-settings.json"
    persist_main_profile(profile, settings_file)
    main = BotProfile(alias="main")
    apply_persisted_main_profile(main, settings_file)
    assert main.cli_type == "codex_server"
    assert main.cli_path == profile.cli_path
    assert main.cli_params.to_dict() == profile.cli_params.to_dict()

    git = GitCommitMessageCliConfig.from_dict(data)
    assert git.cli_type == "codex_server"
    assert git.cli_path == profile.cli_path
    assert GitCommitMessageCliConfig.from_dict(git.to_dict()).to_dict() == git.to_dict()


def test_main_profile_missing_path_uses_codex_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLI_TYPE", "claude")
    monkeypatch.setattr(config, "CLI_PATH", "claude")
    settings_file = tmp_path / "app-settings.json"
    app_settings.update_main_bot_profile({"cli_type": "codex_server"}, settings_file)
    main = BotProfile(alias="main", cli_type="claude", cli_path="claude")
    apply_persisted_main_profile(main, settings_file)
    assert (main.cli_type, main.cli_path) == ("codex_server", "codex")
