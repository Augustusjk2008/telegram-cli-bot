from __future__ import annotations

from pathlib import Path

import pytest

from bot.web.chat_store import ChatStore


def _create_conversation(
    store: ChatStore,
    *,
    agent_id: str = "main",
    title: str = "主会话",
    native_provider: str = "native_agent",
    cli_type: str = "codex",
    parent: str | None = None,
    assignment_revision: int | None = None,
) -> str:
    return store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=2,
        agent_id=agent_id,
        cli_type=cli_type,
        working_dir=str(store.workspace_dir),
        session_epoch=0,
        native_provider=native_provider,
        title=title,
        cluster_parent_conversation_id=parent,
        cluster_assignment_revision=assignment_revision,
    )


def test_cluster_team_cas_conflict_does_not_overwrite(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    conversation_id = _create_conversation(store)
    first_team = {
        "version": 1,
        "assignments": [
            {
                "agent_id": "cluster-slot-1",
                "name": " 后端分析 ",
                "responsibility": " 检查数据层 ",
                "assignment_revision": 1,
            }
        ],
    }
    stale_team = {
        "version": 1,
        "assignments": [
            {
                "agent_id": "cluster-slot-1",
                "name": "其他角色",
                "responsibility": "不应覆盖",
                "assignment_revision": 2,
            }
        ],
    }

    updated = store.update_conversation_team(conversation_id, first_team, expected_revision=0)
    with pytest.raises(Exception) as caught:
        store.update_conversation_team(conversation_id, stale_team, expected_revision=0)

    assert updated["cluster_team_revision"] == 1
    assert updated["cluster_team"]["assignments"][0]["name"] == "后端分析"
    assert getattr(caught.value, "code", "") == "cluster_team_changed"
    assert store.get_conversation_team(conversation_id) == updated


@pytest.mark.parametrize(
    "assignments",
    [
        [{"agent_id": "a", "name": "", "responsibility": "职责", "assignment_revision": 1}],
        [{"agent_id": "a", "name": "名称", "responsibility": "", "assignment_revision": 1}],
        [
            {"agent_id": "a", "name": "重复", "responsibility": "一", "assignment_revision": 1},
            {"agent_id": "b", "name": "重复", "responsibility": "二", "assignment_revision": 1},
        ],
    ],
)
def test_cluster_team_validates_names_responsibilities_and_uniqueness(
    tmp_path: Path,
    assignments: list[dict[str, object]],
) -> None:
    store = ChatStore(tmp_path)
    conversation_id = _create_conversation(store)

    with pytest.raises(ValueError):
        store.update_conversation_team(
            conversation_id,
            {"version": 1, "assignments": assignments},
            expected_revision=0,
        )


def test_child_conversation_binding_can_be_found_by_parent_assignment_and_mode(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    parent = _create_conversation(store)
    child = _create_conversation(
        store,
        agent_id="cluster-slot-1",
        title="子会话",
        parent=parent,
        assignment_revision=3,
    )

    conversation = store.get_conversation(child)
    found = store.find_active_cluster_child_conversation(
        parent_conversation_id=parent,
        agent_id="cluster-slot-1",
        assignment_revision=3,
        execution_mode="native_agent",
    )

    assert conversation["cluster_parent_conversation_id"] == parent
    assert conversation["cluster_assignment_revision"] == 3
    assert found is not None and found["id"] == child
    assert store.find_active_cluster_child_conversation(
        parent_conversation_id=parent,
        agent_id="cluster-slot-1",
        assignment_revision=2,
        execution_mode="native_agent",
    ) is None


def test_child_conversation_binding_keeps_codex_and_codex_server_separate(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    parent = _create_conversation(store)
    codex = _create_conversation(
        store,
        agent_id="cluster-slot-1",
        title="Codex 子会话",
        parent=parent,
        assignment_revision=3,
        native_provider="codex",
        cli_type="codex",
    )
    codex_server = _create_conversation(
        store,
        agent_id="cluster-slot-1",
        title="Codex Server 子会话",
        parent=parent,
        assignment_revision=3,
        native_provider="codex",
        cli_type="codex_server",
    )

    found_codex = store.find_active_cluster_child_conversation(
        parent_conversation_id=parent,
        agent_id="cluster-slot-1",
        assignment_revision=3,
        execution_mode="cli",
        cli_type="codex",
    )
    found_server = store.find_active_cluster_child_conversation(
        parent_conversation_id=parent,
        agent_id="cluster-slot-1",
        assignment_revision=3,
        execution_mode="cli",
        cli_type="codex_server",
    )

    assert found_codex is not None and found_codex["id"] == codex
    assert found_server is not None and found_server["id"] == codex_server


def test_deactivating_child_conversations_preserves_history_but_prevents_runtime_reuse(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    parent = _create_conversation(store)
    child = _create_conversation(
        store,
        agent_id="cluster-slot-1",
        title="历史子会话",
        parent=parent,
        assignment_revision=1,
    )

    assert store.deactivate_cluster_child_conversations(parent) == 1

    saved = store.get_conversation(child)
    assert saved["status"] == "inactive"
    assert store.find_active_cluster_child_conversation(
        parent_conversation_id=parent,
        agent_id="cluster-slot-1",
        assignment_revision=1,
        execution_mode="native_agent",
    ) is None
    assert child in {
        item["id"]
        for item in store.list_conversations(
            bot_id=1,
            user_id=2,
            agent_id="cluster-slot-1",
            working_dir=str(tmp_path),
        )
    }


def test_resize_blockers_include_high_slots_and_exclude_archived_conversations(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    conversation_id = _create_conversation(store, title="旧主会话", native_provider="codex")
    store.update_conversation_team(
        conversation_id,
        {
            "version": 1,
            "assignments": [
                {
                    "agent_id": "cluster-slot-3",
                    "name": "高位角色",
                    "responsibility": "占用第三槽位",
                    "assignment_revision": 1,
                }
            ],
        },
        expected_revision=0,
    )

    blockers = store.list_cluster_resize_blockers(
        bot_id=1,
        slot_agent_ids=["cluster-slot-1", "cluster-slot-2", "cluster-slot-3"],
        target_size=2,
    )

    assert blockers == [
        {
            "conversation_id": conversation_id,
            "title": "旧主会话",
            "execution_mode": "cli",
            "role_count": 1,
            "outside_agent_ids": ["cluster-slot-3"],
            "minimum_size": 3,
        }
    ]

    store.archive_bot_conversations(
        bot_id=1,
        user_id=2,
        working_dir=str(tmp_path),
        agent_id="main",
    )

    assert store.list_cluster_resize_blockers(
        bot_id=1,
        slot_agent_ids=["cluster-slot-1", "cluster-slot-2", "cluster-slot-3"],
        target_size=2,
    ) == []
