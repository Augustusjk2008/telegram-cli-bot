import asyncio
from types import SimpleNamespace

import pytest

from bot.models import BotProfile, GitCommitMessageCliConfig
from bot.web.git_commit_message import extract_commit_message, run_llm_commit_message
from bot.web import git_service
from bot.web.api_common import WebApiError
from bot.web.translation_config import TranslationConfig, TranslationConfigError, TranslationConfigStore
from bot.web.translation_service import TranslationService
import bot.web.chat_translation as chat_translation
import bot.web.translation_config as translation_config_module
import bot.web.translation_service as translation_service_module


class _FakeTranslationClient:
    async def post_chat_completion(self, **_kwargs):
        return {"choices": [{"message": {"content": "你好"}}]}

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_translation_can_use_cli_method(monkeypatch):
    observed = {}

    async def fake_run_cli_prompt(**kwargs):
        observed.update(kwargs)
        return "<TRANSLATION>你好 CLI</TRANSLATION>", 0

    monkeypatch.setattr(translation_service_module, "run_cli_prompt", fake_run_cli_prompt)
    service = TranslationService(client=_FakeTranslationClient())
    try:
        result = await service.translate(
            "hello",
            config=TranslationConfig(method="cli", cli_type="codex", cli_path="codex"),
            direction="user",
        )
    finally:
        await service.close()

    assert result["status"] == "completed"
    assert result["text"] == "你好 CLI"
    assert observed["cli_type"] == "codex"


def test_translation_uses_its_own_cli_settings_instead_of_the_bot_cli(monkeypatch, tmp_path):
    store = TranslationConfigStore(tmp_path / "config.json")
    store.update({
        "method": "cli",
        "cli_type": "claude",
        "cli_path": "claude-translate",
        "cli_params": {"effort": "low", "model": "none"},
    })
    monkeypatch.setattr(chat_translation, "get_translation_service", lambda: SimpleNamespace(config_store=store))
    profile = BotProfile(alias="main", cli_type="codex", cli_path="codex-bot", working_dir=str(tmp_path))

    snapshot = chat_translation.translation_snapshot(profile=profile)

    # Only the working directory follows the chatting Bot.
    assert (snapshot.cli_type, snapshot.cli_path) == ("claude", "claude-translate")
    assert snapshot.cli_working_dir == str(tmp_path)
    # "none" in the model list means the CLI's own default, not a model called none.
    assert snapshot.cli_params["claude"]["effort"] == "low"
    assert snapshot.cli_params["claude"]["model"] is None


def test_saved_translation_cli_settings_load_again_after_a_restart(tmp_path):
    path = tmp_path / "config.json"
    TranslationConfigStore(path).update({
        "method": "cli", "cli_type": "claude", "cli_path": "claude", "cli_params": {"effort": "low"},
    })

    reloaded = TranslationConfigStore(path).get_config()

    assert (reloaded.method, reloaded.cli_type, reloaded.cli_path) == ("cli", "claude", "claude")
    assert reloaded.cli_params["claude"]["effort"] == "low"


def test_enabling_cli_translation_requires_a_runnable_cli(monkeypatch, tmp_path):
    store = TranslationConfigStore(tmp_path / "config.json")
    monkeypatch.setattr(translation_config_module, "resolve_cli_executable", lambda *_args: None)

    with pytest.raises(TranslationConfigError, match="未找到 CLI 可执行文件: missing-cli"):
        store.update({"method": "cli", "cli_path": "missing-cli", "translate_user_enabled": True})

    assert store.get_config().translate_user_enabled is False
    # The CLI can still be prepared while translation is switched off.
    assert store.update({"method": "cli", "cli_path": "missing-cli"})["cli_path"] == "missing-cli"


def test_translation_settings_describe_every_cli_without_host_controlled_parameters():
    options = TranslationConfig().to_public_dict()["cli_options"]

    assert set(options) == {"codex", "codex_server", "claude", "antigravity", "deepseek"}
    for option in options.values():
        assert not {"session_id", "stream_json", "json_output"} & set(option["schema"])
        assert set(option["schema"]) <= set(option["params"])


@pytest.mark.asyncio
async def test_git_commit_message_can_use_llm_method(monkeypatch):
    observed = {}

    class _FakeLlmClient:
        async def post_chat_completion(self, **kwargs):
            assert kwargs["body"]["model"] == "commit-model"
            observed["timeout_seconds"] = kwargs["timeout_seconds"]
            return {"choices": [{"message": {"content": "<COMMIT_MESSAGE>\nfeat: test\n</COMMIT_MESSAGE>"}}]}

        async def close(self):
            return None

    monkeypatch.setattr("bot.web.git_commit_message.OpenAICompatibleClient", _FakeLlmClient)
    config = TranslationConfig(
        base_url="https://example.test/v1",
        api_key="secret",
        model="commit-model",
    )
    response = await run_llm_commit_message(prompt_text="prompt", config=config, timeout_seconds=0.25)
    assert extract_commit_message(response) == "feat: test"
    assert observed["timeout_seconds"] == 0.25


@pytest.mark.asyncio
async def test_git_commit_llm_timeout_closes_the_client(monkeypatch):
    closed = asyncio.Event()

    class _HangingLlmClient:
        async def post_chat_completion(self, **_kwargs):
            await asyncio.sleep(60)

        async def close(self):
            closed.set()

    monkeypatch.setattr("bot.web.git_commit_message.OpenAICompatibleClient", _HangingLlmClient)
    config = TranslationConfig(base_url="https://example.test/v1", api_key="secret", model="commit-model")

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            run_llm_commit_message(prompt_text="prompt", config=config, timeout_seconds=60),
            timeout=0.01,
        )
    assert closed.is_set()


@pytest.mark.asyncio
async def test_git_commit_cli_timeout_terminates_the_process(monkeypatch, tmp_path):
    terminated = False

    class _Manager:
        main_profile = BotProfile(alias="main", cli_type="claude", cli_path="claude", working_dir=str(tmp_path))
        managed_profiles = {}

        def get_git_commit_cli_config(self, _alias):
            return GitCommitMessageCliConfig(
                method="cli",
                cli_type="claude",
                cli_path="claude",
                timeout_seconds=0.01,
            )

    async def hanging_communicate(*_args, **_kwargs):
        await asyncio.sleep(60)

    def terminate(_process):
        nonlocal terminated
        terminated = True

    monkeypatch.setattr(git_service, "resolve_cli_executable", lambda *_args: "claude")
    monkeypatch.setattr(git_service, "build_cli_command", lambda **_kwargs: (["claude"], False))
    monkeypatch.setattr(git_service, "_start_cli_process", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(git_service, "_communicate_process", hanging_communicate)
    monkeypatch.setattr(git_service, "_terminate_process_sync", terminate)
    monkeypatch.setattr(git_service, "close_process_streams", lambda *_args: None)

    with pytest.raises(WebApiError) as exc_info:
        await git_service._generate_git_commit_message_from_context(
            _Manager(),
            "main",
            1,
            repo_root=str(tmp_path),
            context={"status_text": " M file.txt", "diff_text": "diff", "use_staged_diff": False, "diff_truncated": False},
        )

    assert exc_info.value.status == 504
    assert exc_info.value.code == "git_commit_message_timeout"
    assert terminated is True


def test_git_commit_method_round_trips_with_legacy_cli_fields():
    config = GitCommitMessageCliConfig.from_dict({"method": "llm", "cli_type": "codex", "cli_path": "codex"})
    assert config.method == "llm"
    assert GitCommitMessageCliConfig.from_dict(config.to_dict()).method == "llm"
    assert GitCommitMessageCliConfig.from_dict(config.to_dict()).timeout_seconds == 1800
