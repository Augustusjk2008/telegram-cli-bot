from types import SimpleNamespace

import pytest

from bot.models import UserSession
from bot.web import api_service
from bot.web.api_service import _apply_cluster_prompt


def _session() -> UserSession:
    return UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        working_dir="C:/workspace",
    )


def _profile(*, enabled: bool = True, write_policy: str = "main_only") -> SimpleNamespace:
    agents = [SimpleNamespace(id="main"), SimpleNamespace(id="worker")]
    return SimpleNamespace(
        cluster=SimpleNamespace(enabled=enabled, write_policy=write_policy),
        normalized_agents=lambda: agents,
    )


def test_cluster_prompt_encourages_write_for_implementation_tasks_when_allowed() -> None:
    profile = SimpleNamespace(cluster=SimpleNamespace(enabled=True, write_policy="all_agents"))

    prompt = _apply_cluster_prompt(profile, "完成这个实现", cluster_run_id="run-123")

    assert "本轮允许子 agent 写入" in prompt
    assert "实现、修复等需要修改文件的任务" in prompt
    assert "allow_write=true" in prompt
    assert "分析、调研、审查任务保持只读" in prompt


def test_cluster_prompt_keeps_child_tasks_read_only_when_write_is_disallowed() -> None:
    profile = SimpleNamespace(cluster=SimpleNamespace(enabled=True, write_policy="main_only"))

    prompt = _apply_cluster_prompt(profile, "完成这个实现", cluster_run_id="run-123")

    assert "本轮仅主 agent 可写" in prompt
    assert "不要设置 allow_write=true" in prompt


def test_cluster_prompt_keeps_same_run_id_after_full_session_prompt() -> None:
    profile = _profile()
    session = _session()

    first = _apply_cluster_prompt(
        profile,
        "第一轮",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
        cluster_run_id="run-1",
    )
    second = _apply_cluster_prompt(
        profile,
        "第二轮",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
        cluster_run_id="run-1",
    )

    assert "简单、不可并行或委派成本更高" in first
    assert "当前 run_id: run-1" in first
    assert "简单、不可并行或委派成本更高" not in second
    assert "沿用本会话此前的集群规则" in second
    assert "当前 run_id: run-1" in second
    assert "普通轮次继续使用当前 run_id" in second
    assert "changed=true" in second
    assert "changed=false" in second
    assert "run-2" not in second


def test_cluster_disabled_prompt_is_not_repeated_in_same_session() -> None:
    profile = _profile(enabled=False)
    session = _session()

    first = _apply_cluster_prompt(
        profile,
        "第一轮",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
    )
    second = _apply_cluster_prompt(
        profile,
        "第二轮",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
    )

    assert "集群模式已关闭" in first
    assert second == "第二轮"


def test_cluster_prompt_is_reinjected_when_mode_or_write_policy_changes() -> None:
    profile = _profile(enabled=False)
    session = _session()

    _apply_cluster_prompt(
        profile,
        "关闭",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
    )
    profile.cluster.enabled = True
    enabled = _apply_cluster_prompt(
        profile,
        "启用",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
        cluster_run_id="run-1",
    )
    profile.cluster.write_policy = "all_agents"
    policy_changed = _apply_cluster_prompt(
        profile,
        "策略变化",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
        cluster_run_id="run-1",
    )
    profile.cluster.enabled = False
    disabled = _apply_cluster_prompt(
        profile,
        "再次关闭",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
    )

    assert "简单、不可并行或委派成本更高" in enabled
    assert "本轮允许子 agent 写入" in policy_changed
    assert "简单、不可并行或委派成本更高" in policy_changed
    assert "集群模式已关闭" in disabled


def test_cluster_prompt_is_reinjected_for_a_new_or_reset_model_session() -> None:
    profile = _profile()
    session = _session()

    _apply_cluster_prompt(
        profile,
        "旧会话首轮",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
        cluster_run_id="run-1",
    )
    same_session = _apply_cluster_prompt(
        profile,
        "旧会话次轮",
        session=session,
        context_kind="cli:codex",
        context_id="session-1",
        cluster_run_id="run-1",
    )
    changed_session = _apply_cluster_prompt(
        profile,
        "新会话",
        session=session,
        context_kind="cli:codex",
        context_id="session-2",
        cluster_run_id="run-1",
    )
    reset_session = _apply_cluster_prompt(
        profile,
        "重建中",
        session=session,
        context_kind="cli:codex",
        context_id="",
        cluster_run_id="run-1",
    )

    assert "简单、不可并行或委派成本更高" not in same_session
    assert "简单、不可并行或委派成本更高" in changed_session
    assert "简单、不可并行或委派成本更高" in reset_session
    assert "当前 run_id: run-1" in same_session
    assert "当前 run_id: run-1" in changed_session
    assert "当前 run_id: run-1" in reset_session


def test_cluster_prompt_can_force_full_guidance_for_same_turn_session_retry() -> None:
    profile = _profile()
    session = _session()

    _apply_cluster_prompt(
        profile,
        "首轮",
        session=session,
        context_kind="cli:claude",
        context_id="session-1",
        cluster_run_id="run-1",
    )
    retry = _apply_cluster_prompt(
        profile,
        "重试",
        session=session,
        context_kind="cli:claude",
        context_id="",
        cluster_run_id="run-1",
        force_full=True,
    )

    assert "简单、不可并行或委派成本更高" in retry
    assert "当前 run_id: run-1" in retry


@pytest.mark.asyncio
async def test_native_chat_keeps_full_cluster_prompt_as_new_session_fallback(monkeypatch) -> None:
    profile = _profile()
    profile.alias = "main"
    profile.cli_type = "codex"
    session = _session()
    session.native_agent_session_id = "pi-session-1"
    calls: list[dict[str, object]] = []
    run_ids = iter(["run-1", "run-1"])

    class FakeService:
        async def run_chat(self, **kwargs):
            calls.append(kwargs)
            return {"output": "done"}

    async def ensure_conversation(*_args, **_kwargs):
        return "conversation-1", {}

    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args: (profile, SimpleNamespace(id="main"), session),
    )
    monkeypatch.setattr(api_service, "_ensure_cluster_main_conversation", ensure_conversation)
    monkeypatch.setattr(
        api_service,
        "_start_cluster_run_if_requested",
        lambda **_kwargs: SimpleNamespace(run_id=next(run_ids)),
    )
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeService())
    monkeypatch.setattr(api_service, "_history_service_for_execution_mode", lambda *_args: object())
    monkeypatch.setattr(api_service._CLUSTER_RUNTIME, "finish_run", lambda *_args: None)
    monkeypatch.setattr(api_service, "_cleanup_cluster_run_control_if_idle", lambda *_args: None)

    await api_service._run_native_agent_chat(None, "main", 1001, "第一轮")
    await api_service._run_native_agent_chat(None, "main", 1001, "第二轮")

    assert "简单、不可并行或委派成本更高" in str(calls[0]["prompt_text"])
    assert "简单、不可并行或委派成本更高" not in str(calls[1]["prompt_text"])
    assert "当前 run_id: run-1" in str(calls[1]["prompt_text"])
    assert "简单、不可并行或委派成本更高" in str(calls[1]["fresh_session_prompt_text"])
    assert "当前 run_id: run-1" in str(calls[1]["fresh_session_prompt_text"])
