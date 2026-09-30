from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bot.cli_params import CliParamsConfig
from bot.models import BotProfile, GitCommitMessageCliConfig
from bot.web.git_commit_message import build_git_commit_cli_config, run_codex_server_commit_message, truncate_diff_text


def test_truncate_diff_text_balances_budget_across_files() -> None:
    summary = "3 files changed, 300 insertions(+), 300 deletions(-)\n"
    file_diffs = [
        (
            f"diff --git a/{name}.txt b/{name}.txt\n"
            f"index 1111111..2222222 100644\n"
            f"--- a/{name}.txt\n"
            f"+++ b/{name}.txt\n"
            "@@ -1 +1 @@\n"
            f"-{marker}-old-" + "x" * 400 + "\n"
            f"+{marker}-new-" + "y" * 400 + "\n"
        )
        for name, marker in [("alpha", "ALPHA"), ("beta", "BETA"), ("gamma", "GAMMA")]
    ]

    result, truncated = truncate_diff_text(summary + "".join(file_diffs), limit=600)

    assert truncated is True
    assert summary.strip() in result
    for name, marker in [("alpha", "ALPHA"), ("beta", "BETA"), ("gamma", "GAMMA")]:
        assert f"diff --git a/{name}.txt b/{name}.txt" in result
        assert marker in result


def test_truncate_diff_text_reuses_budget_left_by_small_files() -> None:
    small = "diff --git a/small.txt b/small.txt\n-small\n+small change\n"
    large_a = "diff --git a/large-a.txt b/large-a.txt\n" + "A" * 1_000 + "\n"
    large_b = "diff --git a/large-b.txt b/large-b.txt\n" + "B" * 1_000 + "\n"

    result, truncated = truncate_diff_text(small + large_a + large_b, limit=600)

    content = result.removesuffix("\n\n...[truncated]")
    assert truncated is True
    assert len(content) >= 580
    assert "A" * 200 in content
    assert "B" * 200 in content


@pytest.mark.parametrize("cli_type", ["", "codex_server"])
def test_git_commit_config_preserves_selected_or_inherited_server_backend(cli_type):
    params = CliParamsConfig.from_dict({
        "codex": {"model": "exec-model"}, "codex_server": {"model": "server-model"},
    })
    result = build_git_commit_cli_config(
        BotProfile(alias="main", cli_type="codex_server"),
        GitCommitMessageCliConfig(cli_type=cli_type, cli_path="codex", cli_params=params),
    )
    assert result["cli_type"] == "codex_server"
    assert result["params"]["model"] == "server-model"
    assert "reasoning_effort" in result["schema"]


@pytest.mark.asyncio
async def test_git_service_routes_server_generation_without_exec(monkeypatch):
    from bot.web import git_commit_message, git_service

    cli_config = GitCommitMessageCliConfig(cli_type="codex_server", cli_path="codex")
    manager = SimpleNamespace(get_git_commit_cli_config=lambda alias: cli_config)
    monkeypatch.setattr(git_service, "get_profile_or_raise", lambda *_: BotProfile(alias="main"))
    monkeypatch.setattr(git_service, "resolve_cli_executable", lambda *_: "resolved-codex")
    monkeypatch.setattr(git_service, "build_commit_message_prompt", lambda **_: "diff prompt")
    monkeypatch.setattr(git_service, "build_cli_command", Mock(side_effect=AssertionError("exec must not be used")))
    capture = AsyncMock(return_value=object())
    record = AsyncMock()
    monkeypatch.setattr(git_service, "start_codex_rate_limit_capture", capture)
    monkeypatch.setattr(git_service, "record_codex_rate_limit_capture", record)
    raw = "\n".join(json.dumps(event) for event in [
        {"type": "thread.started", "thread_id": "git-only-thread"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "<COMMIT_MESSAGE>修复</COMMIT_MESSAGE>"}},
    ])
    run = AsyncMock(return_value=(raw, 0))
    monkeypatch.setattr(git_commit_message, "run_codex_server_commit_message", run)

    result = await git_service._generate_git_commit_message_from_context(
        manager, "main", 1, repo_root="repo", context={},
    )

    assert result == {"message": "修复"}
    run.assert_awaited_once()
    assert run.call_args.kwargs["resolved_cli"] == "resolved-codex"
    assert run.call_args.kwargs["prompt_text"] == "diff prompt"
    record.assert_awaited_once()
    assert record.call_args.args[1].session_id == "git-only-thread"


@pytest.fixture
def server_registry(monkeypatch):
    from bot.codex_server import runtime

    registries = []

    def create():
        registry = SimpleNamespace(open_or_create=AsyncMock(), aclose=AsyncMock())
        registries.append(registry)
        return registry

    factory = Mock(side_effect=create)
    monkeypatch.setattr(runtime, "CodexServerRegistry", factory)
    monkeypatch.setattr(runtime, "get_codex_server_registry", Mock(
        side_effect=AssertionError("chat registry must not be used"),
    ))
    return factory, registries


@pytest.mark.asyncio
async def test_codex_server_commit_message_uses_fresh_isolated_runtime(server_registry):
    factory, registries = server_registry
    prompts = []
    event = {"type": "item.completed", "item": {"type": "agent_message", "text": "<COMMIT_MESSAGE>修复</COMMIT_MESSAGE>"}}

    async def stream_turn(prompt):
        prompts.append(prompt)
        yield event

    create = factory.side_effect

    def create_runtime():
        registry = create()
        registry.open_or_create.return_value = SimpleNamespace(stream_turn=stream_turn, returncode=0)
        return registry

    factory.side_effect = create_runtime
    env = {"CODEX_HOME": "isolated-home"}
    params = CliParamsConfig()
    for _ in range(2):
        raw, returncode = await run_codex_server_commit_message(
            resolved_cli="custom-codex", prompt_text="diff prompt", repo_root="repo",
            env=env, params_config=params,
        )
        assert json.loads(raw) == event and returncode == 0

    first, second = [registry.open_or_create.call_args.args[0] for registry in registries]
    assert first.conversation_id != second.conversation_id
    assert first.thread_id == second.thread_id == ""
    assert first.command == "custom-codex" and first.cwd == "repo"
    assert first.env == env and first.env is not env
    assert first.params_config.to_dict() == params.to_dict() and first.params_config is not params
    assert prompts == ["diff prompt", "diff prompt"]
    for registry in registries:
        registry.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["open", "stream", "cancel", "incomplete", "failed"])
async def test_codex_server_commit_message_always_closes_without_retry(server_registry, phase):
    factory, registries = server_registry
    started = asyncio.Event()

    async def stream_turn(prompt):
        if phase == "cancel":
            started.set()
            await asyncio.Event().wait()
        if phase == "stream":
            raise RuntimeError("protocol failure")
        yield {"type": "turn.failed", "error": {"message": "failed"}}

    create = factory.side_effect

    def create_runtime():
        registry = create()
        if phase == "open":
            registry.open_or_create.side_effect = RuntimeError("protocol failure")
        else:
            registry.open_or_create.return_value = SimpleNamespace(
                stream_turn=stream_turn, returncode=None if phase == "incomplete" else 1,
            )
        return registry

    factory.side_effect = create_runtime
    task = asyncio.create_task(run_codex_server_commit_message(
        resolved_cli="codex", prompt_text="diff", repo_root="repo", env={}, params_config=CliParamsConfig(),
    ))
    if phase == "cancel":
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif phase == "failed":
        _, returncode = await task
        assert returncode == 1
    else:
        with pytest.raises(RuntimeError):
            await task
    factory.assert_called_once()
    registries[0].open_or_create.assert_awaited_once()
    registries[0].aclose.assert_awaited_once()
