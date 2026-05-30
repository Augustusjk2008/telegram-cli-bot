"""测试 assistant 模式收敛后的兼容行为。"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from bot.assistant.cron.store import load_job_runtime_state
from bot.assistant.cron.types import AssistantCronJob
from bot.assistant.home import bootstrap_assistant_home
from bot.models import BotProfile


class TestAssistantMode:
    def test_bot_profile_keeps_assistant_mode(self):
        profile = BotProfile(alias="assistant1", token="test_token", bot_mode="assistant")
        assert profile.bot_mode == "assistant"
        assert profile.to_dict()["bot_mode"] == "assistant"

class TestMultiBotManagerWithAssistant:
    @pytest.mark.asyncio
    async def test_load_assistant_profile_from_json(self, temp_dir):
        from bot.manager import MultiBotManager

        config_file = temp_dir / "test_bots.json"
        config_file.write_text(
            json.dumps(
                {
                    "bots": [
                        {
                            "alias": "assistant1",
                            "token": "test_token_123",
                            "bot_mode": "assistant",
                            "working_dir": str(temp_dir),
                            "enabled": True,
                            "cli_type": "codex",
                            "cli_path": "codex",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        manager = MultiBotManager(
            BotProfile(alias="main", token="main_token", working_dir=str(temp_dir)),
            str(config_file),
        )

        assert "assistant1" in manager.managed_profiles
        profile = manager.managed_profiles["assistant1"]
        assert profile.bot_mode == "assistant"
        assert profile.alias == "assistant1"
        assert profile.enabled is True

    @pytest.mark.asyncio
    async def test_add_assistant_bot(self, temp_dir):
        from bot.manager import MultiBotManager

        config_file = temp_dir / "test_bots.json"
        main_profile = BotProfile(alias="main", token="main_token", working_dir=str(temp_dir))
        manager = MultiBotManager(main_profile, str(config_file))

        with patch("bot.manager.resolve_cli_executable", return_value="codex"), \
             patch.object(manager, "_start_profile", new_callable=AsyncMock):
            profile = await manager.add_bot(
                alias="test_assistant",
                token="test_token",
                cli_type="codex",
                cli_path="codex",
                working_dir=str(temp_dir),
                bot_mode="assistant",
            )

        assert profile.bot_mode == "assistant"
        assert profile.alias == "test_assistant"
        assert "test_assistant" in manager.managed_profiles

@pytest.mark.asyncio
async def test_assistant_runtime_snapshot_reports_active_and_queued_runs():
    from bot.assistant.runtime import AssistantRunRequest, AssistantRuntimeCoordinator

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_result_executor(_request: AssistantRunRequest):
        started.set()
        await release.wait()
        return {"status": "completed"}

    runtime = AssistantRuntimeCoordinator(result_executor=blocking_result_executor)
    await runtime.start()

    running_request = AssistantRunRequest(
        run_id="run_active_1",
        source="cron",
        bot_alias="assistant1",
        user_id=-1,
        text="dream prompt",
        interactive=False,
        visible_text="dream prompt",
        task_mode="dream",
        job_id="daily_dream",
        job_title="每日自整理",
        enqueued_at="2026-04-28T10:30:00+08:00",
    )
    queued_request = AssistantRunRequest(
        run_id="run_queued_1",
        source="web",
        bot_alias="assistant1",
        user_id=1001,
        text="帮我总结今天进度",
        interactive=True,
        visible_text="帮我总结今天进度",
        enqueued_at="2026-04-28T10:30:01+08:00",
    )

    await runtime.submit_background(running_request)
    await runtime.submit_background(queued_request)
    await asyncio.wait_for(started.wait(), timeout=1)

    snapshot = runtime.snapshot_for_bot("assistant1")

    assert snapshot["pending_count"] == 2
    assert snapshot["queued_count"] == 1
    assert snapshot["active"]["run_id"] == "run_active_1"
    assert snapshot["active"]["job_title"] == "每日自整理"
    assert snapshot["queue"][0]["run_id"] == "run_queued_1"
    assert snapshot["queue"][0]["source"] == "web"

    release.set()
    await asyncio.wait_for(runtime.wait_for_run(running_request.run_id), timeout=1)
    await asyncio.wait_for(runtime.wait_for_run(queued_request.run_id), timeout=1)
    await runtime.stop()


