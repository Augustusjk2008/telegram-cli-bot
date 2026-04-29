from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput
from bot.assistant_proposals import create_proposal
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.server import WebApiServer


@pytest.fixture
def web_manager(temp_dir: Path) -> MultiBotManager:
    storage_file = temp_dir / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(temp_dir),
        enabled=True,
    )
    return MultiBotManager(main_profile=profile, storage_file=str(storage_file))


def _enable_local_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])


def _add_assistant_profile(web_manager: MultiBotManager, workdir: Path) -> None:
    web_manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(workdir),
        enabled=True,
        bot_mode="assistant",
    )


@pytest.mark.asyncio
async def test_admin_assistant_proposal_detail_returns_diff_and_apply_state(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="scope", body="assistant 单例")
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}"
            )

            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["proposal"]["id"] == proposal["id"]
            assert payload["data"]["diff"]["available"] is True
            assert "diff --git" in payload["data"]["diff"]["text"]
            assert payload["data"]["apply"]["available"] is True
            assert payload["data"]["apply"]["applied"] is False


@pytest.mark.asyncio
async def test_admin_assistant_proposal_detail_404_for_missing_id(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/bots/assistant1/assistant/proposals/pr_missing")

            assert resp.status == 404
            payload = await resp.json()
            assert payload["error"]["code"] == "proposal_not_found"


@pytest.mark.asyncio
async def test_admin_assistant_proposal_apply_rejects_non_approved_proposal(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/upgrades/{proposal['id']}/apply"
            )

            assert resp.status == 409
            payload = await resp.json()
            assert payload["error"]["code"] == "proposal_not_approved"


@pytest.mark.asyncio
async def test_admin_assistant_proposal_apply_404_for_missing_patch(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/upgrades/{proposal['id']}/apply"
            )

            assert resp.status == 404
            payload = await resp.json()
            assert payload["error"]["code"] == "upgrade_patch_not_found"


@pytest.mark.asyncio
async def test_admin_assistant_proposal_detail_pending_patch_is_not_applyable(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="pending patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    patch_path = home.root / "upgrades" / "pending" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}"
            )
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["diff"]["available"] is True
            assert payload["data"]["diff"]["source"] == f"upgrades/pending/{proposal['id']}.patch"
            assert payload["data"]["diff"]["state"] == "pending"
            assert payload["data"]["apply"]["available"] is False


@pytest.mark.asyncio
async def test_admin_assistant_proposal_apply_failure_writes_last_error_audit(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            error = subprocess.CalledProcessError(
                1,
                ["git", "apply", "--check", str(patch_path)],
                stderr="patch does not apply",
            )
            with patch("bot.assistant_upgrade.subprocess.run", side_effect=error):
                resp = await client.post(
                    f"/api/admin/bots/assistant1/assistant/upgrades/{proposal['id']}/apply"
                )

            assert resp.status == 500
            payload = await resp.json()
            assert payload["error"]["code"] == "assistant_upgrade_failed"
            audit_path = home.root / "upgrades" / "applied" / f"{proposal['id']}.last-error.json"
            assert audit_path.exists()
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            assert audit["status"] == "failed"
            assert "patch does not apply" in audit["error"]


@pytest.mark.asyncio
async def test_admin_assistant_upgrade_apply_log_route_returns_last_error(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    audit_path = home.root / "upgrades" / "applied" / f"{proposal['id']}.last-error.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "id": proposal["id"],
                "status": "failed",
                "failed_at": "2026-04-28T00:00:00+00:00",
                "error": "patch does not apply",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}/apply-log"
            )

            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["status"] == "failed"
            assert payload["data"]["error"] == "patch does not apply"


@pytest.mark.asyncio
async def test_admin_assistant_memory_search_and_invalidate(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    memory_id = AssistantMemoryStore(home).upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_1",
            title="默认语言",
            summary="默认中文",
            body="- 默认中文",
            tags=["preference"],
            entity_keys=["user:1001"],
        )
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/bots/assistant1/assistant/memory/search?query=默认中文&user_id=1001")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["items"][0]["id"] == memory_id

            invalidate_resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/memory/{memory_id}/invalidate",
                json={"reason": "web_admin"},
            )
            assert invalidate_resp.status == 200
            invalidate_payload = await invalidate_resp.json()
            assert invalidate_payload["data"]["invalidated"] is True

    rows = AssistantMemoryStore(home).search_lexical(user_id=1001, query_text="默认中文")
    assert rows == []


@pytest.mark.asyncio
async def test_admin_assistant_memory_search_defaults_to_authenticated_user(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 2002)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    AssistantMemoryStore(home).upsert(
        MemoryRecordInput(
            user_id=2002,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_2002",
            title="用户 2002 偏好",
            summary="只属于 2002 的记忆",
            body="- only-user-2002",
            tags=[],
            entity_keys=[],
        )
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            default_resp = await client.get(
                "/api/admin/bots/assistant1/assistant/memory/search?query=only-user-2002"
            )
            forced_resp = await client.get(
                "/api/admin/bots/assistant1/assistant/memory/search?query=only-user-2002&user_id=1001"
            )

            assert default_resp.status == 200
            assert forced_resp.status == 200
            default_payload = await default_resp.json()
            forced_payload = await forced_resp.json()
            assert len(default_payload["data"]["items"]) == 1
            assert forced_payload["data"]["items"] == []


@pytest.mark.asyncio
async def test_admin_assistant_memory_reindex_emits_diagnostics_record(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    (home.root / "memory" / "working" / "current_goal.md").write_text("- 修 proposal UI\n", encoding="utf-8")
    knowledge_dir = home.root / "memory" / "knowledge" / "ops"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    (knowledge_dir / "checklist.md").write_text("# Checklist\n- 审批 proposal\n", encoding="utf-8")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            reindex_resp = await client.post(
                "/api/admin/bots/assistant1/assistant/memory/reindex",
                json={"user_id": 1001, "force": True},
            )
            assert reindex_resp.status == 200
            reindex_payload = await reindex_resp.json()
            assert reindex_payload["data"]["working"]["indexed_count"] >= 1
            assert reindex_payload["data"]["knowledge"]["indexed_count"] >= 1

            diagnostics_resp = await client.get("/api/admin/bots/assistant1/assistant/diagnostics/perf?limit=5")
            assert diagnostics_resp.status == 200
            diagnostics_payload = await diagnostics_resp.json()
            assert diagnostics_payload["data"]["items"][0]["source"] == "memory_reindex"
            assert diagnostics_payload["data"]["items"][0]["stage_durations"]["index_ms"] >= 0


@pytest.mark.asyncio
async def test_admin_assistant_memory_eval_run_and_reports(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    AssistantMemoryStore(home).upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_eval",
            title="默认语言",
            summary="默认中文",
            body="- 默认中文",
            tags=["preference"],
            entity_keys=["user:1001"],
        )
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            eval_resp = await client.post(
                "/api/admin/bots/assistant1/assistant/evals/memory/run",
                json={
                    "user_id": 1001,
                    "cases": [
                        {
                            "query": "默认中文",
                            "expected_memory_kind": "semantic",
                            "expected_hit_terms": ["默认中文"],
                            "must_not_hit_terms": ["默认英文"],
                        }
                    ],
                },
            )
            assert eval_resp.status == 200
            eval_payload = await eval_resp.json()
            assert eval_payload["data"]["metrics"]["hit_at_5"] == 1.0

            reports_resp = await client.get("/api/admin/bots/assistant1/assistant/evals/memory/reports?limit=5")
            assert reports_resp.status == 200
            reports_payload = await reports_resp.json()
            assert reports_payload["data"]["items"][0]["metrics"]["hit_at_5"] == 1.0
