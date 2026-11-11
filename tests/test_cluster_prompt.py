from types import SimpleNamespace


from bot.models import UserSession
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

    assert "Sub-agents may write files this turn" in prompt
    assert "allow_write=true" in prompt


def test_cluster_prompt_keeps_child_tasks_read_only_when_write_is_disallowed() -> None:
    profile = SimpleNamespace(cluster=SimpleNamespace(enabled=True, write_policy="main_only"))

    prompt = _apply_cluster_prompt(profile, "完成这个实现", cluster_run_id="run-123")

    assert "Only the main agent may write files this turn" in prompt
    assert "do not set allow_write=true" in prompt


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

    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" in first
    assert "Current run_id: run-1" in first
    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" not in second
    assert "Current run_id: run-1" in second
    assert "Continue using the current run_id for ordinary turns" in second
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

    assert "Cluster mode is disabled" in first
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

    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" in enabled
    assert "Sub-agents may write files this turn" in policy_changed
    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" in policy_changed
    assert "Cluster mode is disabled" in disabled


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

    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" not in same_session
    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" in changed_session
    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" in reset_session
    assert "Current run_id: run-1" in same_session
    assert "Current run_id: run-1" in changed_session
    assert "Current run_id: run-1" in reset_session


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

    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" in retry
    assert "Current run_id: run-1" in retry
