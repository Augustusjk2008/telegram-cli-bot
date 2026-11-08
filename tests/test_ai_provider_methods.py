import pytest

from bot.models import GitCommitMessageCliConfig
from bot.web.git_commit_message import extract_commit_message, run_llm_commit_message
from bot.web.translation_config import TranslationConfig
from bot.web.translation_service import TranslationService
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


@pytest.mark.asyncio
async def test_git_commit_message_can_use_llm_method(monkeypatch):
    class _FakeLlmClient:
        async def post_chat_completion(self, **kwargs):
            assert kwargs["body"]["model"] == "commit-model"
            return {"choices": [{"message": {"content": "<COMMIT_MESSAGE>\nfeat: test\n</COMMIT_MESSAGE>"}}]}

        async def close(self):
            return None

    monkeypatch.setattr("bot.web.git_commit_message.OpenAICompatibleClient", _FakeLlmClient)
    config = TranslationConfig(
        base_url="https://example.test/v1",
        api_key="secret",
        model="commit-model",
    )
    response = await run_llm_commit_message(prompt_text="prompt", config=config)
    assert extract_commit_message(response) == "feat: test"


def test_git_commit_method_round_trips_with_legacy_cli_fields():
    config = GitCommitMessageCliConfig.from_dict({"method": "llm", "cli_type": "codex", "cli_path": "codex"})
    assert config.method == "llm"
    assert GitCommitMessageCliConfig.from_dict(config.to_dict()).method == "llm"
