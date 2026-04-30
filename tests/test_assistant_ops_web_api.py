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


def _init_git_repo(repo: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=repo, text=True).strip()


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
            assert payload["data"]["upgrade"]["state"] == "approved"


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
            assert payload["data"]["upgrade"]["state"] == "pending"


@pytest.mark.asyncio
async def test_admin_assistant_proposal_detail_failed_patch_generation_reports_failed_state(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="failed patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata_path = home.root / "upgrades" / "pending" / f"{proposal['id']}.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "id": proposal["id"],
                "proposal_id": proposal["id"],
                "state": "pending",
                "lifecycle": "failed",
                "generator": {"status": "failed", "elapsed_seconds": 2},
                "error": "cli failed",
                "sensitive_hits": [],
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
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}"
            )
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["upgrade"]["state"] == "failed"
            assert payload["data"]["upgrade"]["generation_status"] == "failed"
            assert payload["data"]["upgrade"]["can_approve_patch"] is False
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
async def test_admin_assistant_upgrade_targets_list_git_repos(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    repo = temp_dir / "target-repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    web_manager.managed_profiles["target1"] = BotProfile(
        alias="target1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(repo),
        enabled=True,
        bot_mode="cli",
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/bots/assistant1/assistant/upgrade-targets")
            assert resp.status == 200
            payload = await resp.json()

    items = payload["data"]["items"]
    target = next(item for item in items if item["alias"] == "target1")
    assert target["available"] is True
    assert target["repo_root"] == str(repo.resolve())
    assert len(target["head"]) >= 7


@pytest.mark.asyncio
async def test_admin_assistant_generate_patch_requires_approved_proposal(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    assistant_dir = temp_dir / "assistant-root"
    assistant_dir.mkdir()
    _add_assistant_profile(web_manager, assistant_dir)
    home = bootstrap_assistant_home(assistant_dir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}/patch",
                json={"target_alias": "main"},
            )
            assert resp.status == 409
            payload = await resp.json()
            assert payload["error"]["code"] == "proposal_not_approved"


@pytest.mark.asyncio
async def test_admin_assistant_generate_and_approve_patch_api(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    assistant_dir = temp_dir / "assistant-root"
    assistant_dir.mkdir()
    repo = temp_dir / "target"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "a.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    _add_assistant_profile(web_manager, assistant_dir)
    web_manager.managed_profiles["target1"] = BotProfile(
        alias="target1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(repo),
        enabled=True,
        bot_mode="cli",
    )
    home = bootstrap_assistant_home(assistant_dir)
    proposal = create_proposal(home, kind="code", title="patch", body="change a")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    def fake_generate(home_arg, proposal_arg, *, target, generated_by, regenerate=False):
        patch_path = home_arg.root / "upgrades" / "pending" / f"{proposal_arg['id']}.patch"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")
        metadata = {
            "id": proposal_arg["id"],
            "proposal_id": proposal_arg["id"],
            "state": "pending",
            "target_alias": target["alias"],
            "target_working_dir": target["working_dir"],
            "target_repo_root": target["repo_root"],
            "base_commit": target["head"],
            "worktree_path": str(home_arg.root / "upgrades" / "worktrees" / proposal_arg["id"]),
            "patch_path": f"upgrades/pending/{proposal_arg['id']}.patch",
            "generated_at": "2026-04-29T00:00:00+00:00",
            "generated_by": generated_by,
            "generator": {"cli_type": "codex", "cli_path": "codex", "status": "succeeded", "elapsed_seconds": 1},
            "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
            "sensitive_hits": [],
            "changed_files": ["a.txt"],
            "additions": 1,
            "deletions": 0,
        }
        (home_arg.root / "upgrades" / "pending" / f"{proposal_arg['id']}.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return metadata

    monkeypatch.setattr("bot.web.api_service.generate_pending_patch", fake_generate)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            generate_resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}/patch",
                json={"target_alias": "target1"},
            )
            assert generate_resp.status == 200
            detail_resp = await client.get(f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}")
            assert detail_resp.status == 200
            detail = await detail_resp.json()
            assert detail["data"]["diff"]["state"] == "pending"
            assert detail["data"]["upgrade"]["state"] == "pending"
            approve_resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}/patch/approve"
            )
            assert approve_resp.status == 200

    assert (home.root / "upgrades" / "approved" / f"{proposal['id']}.patch").exists()


@pytest.mark.asyncio
async def test_admin_assistant_generate_patch_stream_api(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    assistant_dir = temp_dir / "assistant-root"
    assistant_dir.mkdir()
    repo = temp_dir / "target"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "a.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    _add_assistant_profile(web_manager, assistant_dir)
    web_manager.managed_profiles["target1"] = BotProfile(
        alias="target1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(repo),
        enabled=True,
        bot_mode="cli",
    )
    home = bootstrap_assistant_home(assistant_dir)
    proposal = create_proposal(home, kind="code", title="patch", body="change a")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    async def fake_stream(*args, **kwargs):
        yield {"type": "status", "phase": "setup", "message": "准备生成", "lifecycle": "running"}
        yield {"type": "trace", "event": {"kind": "commentary", "summary": "已创建 worktree"}}
        yield {
            "type": "done",
            "metadata": {
                "id": proposal["id"],
                "proposal_id": proposal["id"],
                "state": "pending",
                "lifecycle": "pending",
                "target_alias": "target1",
                "target_working_dir": str(repo),
                "target_repo_root": str(repo),
                "base_commit": "deadbeef",
                "worktree_path": str(home.root / "upgrades" / "worktrees" / proposal["id"]),
                "patch_path": f"upgrades/pending/{proposal['id']}.patch",
                "generated_at": "2026-04-30T00:00:00+00:00",
                "generated_by": "1001",
                "generator": {"cli_type": "codex", "cli_path": "codex", "status": "succeeded", "elapsed_seconds": 2},
                "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
                "sensitive_hits": [],
                "changed_files": ["a.txt"],
                "additions": 1,
                "deletions": 0,
            },
        }

    monkeypatch.setattr("bot.web.server.stream_generate_assistant_proposal_patch", fake_stream)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}/patch/stream",
                json={"target_alias": "target1"},
            )
            assert resp.status == 200
            text = await resp.text()

    assert "event: status" in text
    assert "event: trace" in text
    assert "event: done" in text
    assert f"\"proposal_id\": \"{proposal['id']}\"" in text


@pytest.mark.asyncio
async def test_admin_assistant_dry_run_uses_metadata_target_repo(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    assistant_dir = temp_dir / "assistant-root"
    assistant_dir.mkdir()
    target_repo = temp_dir / "target"
    target_repo.mkdir()
    _add_assistant_profile(web_manager, assistant_dir)
    home = bootstrap_assistant_home(assistant_dir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")
    (home.root / "upgrades" / "approved" / f"{proposal['id']}.json").write_text(
        json.dumps({"state": "approved", "target_repo_root": str(target_repo)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    seen = {}

    def fake_dry_run(*, repo_root: Path, patch_path: Path):
        seen["repo_root"] = repo_root
        return {"ok": True, "checked_at": "now", "stdout": "", "stderr": "", "patch_path": str(patch_path), "repo_root": str(repo_root)}

    monkeypatch.setattr("bot.web.api_service.run_upgrade_dry_run", fake_dry_run)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post(f"/api/admin/bots/assistant1/assistant/upgrades/{proposal['id']}/dry-run")
            assert resp.status == 200

    assert seen["repo_root"] == target_repo.resolve()


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


@pytest.mark.asyncio
async def test_admin_assistant_diagnostics_filters_and_summarizes(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)

    from bot.assistant_perf import write_perf_record

    write_perf_record(
        home,
        run_id="run_ok",
        bot_alias="assistant1",
        source="web",
        task_mode="standard",
        interactive=True,
        user_id=1001,
        status="completed",
        stage_durations={"cli_ms": 100, "recall_ms": 20},
        elapsed_ms=150,
    )
    write_perf_record(
        home,
        run_id="run_failed",
        bot_alias="assistant1",
        source="cron",
        task_mode="dream",
        interactive=False,
        user_id=1002,
        status="failed",
        stage_durations={"cli_ms": 1200, "db_ms": 30},
        elapsed_ms=1300,
        error="patch does not apply",
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get(
                "/api/admin/bots/assistant1/assistant/diagnostics/perf?status=failed&source=cron&user_id=1002&limit=20"
            )
            assert resp.status == 200
            payload = await resp.json()

    data = payload["data"]
    assert [item["run_id"] for item in data["items"]] == ["run_failed"]
    assert data["summary"]["total"] == 1
    assert data["summary"]["failed"] == 1
    assert data["summary"]["by_source"]["cron"] == 1
    assert data["summary"]["by_status"]["failed"] == 1
    assert data["summary"]["slow_stages"][0]["stage"] == "cli_ms"
    assert data["summary"]["error_groups"][0]["message"] == "patch does not apply"


@pytest.mark.asyncio
async def test_admin_assistant_memory_filters_include_invalidated_and_bulk_invalidate(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    store = AssistantMemoryStore(home)
    semantic_id = store.upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="s1",
            title="默认语言",
            summary="默认中文",
            body="默认中文",
            tags=[],
            entity_keys=[],
        )
    )
    procedural_id = store.upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="project",
            kind="procedural",
            source_type="test",
            source_ref="p1",
            title="操作步骤",
            summary="重启流程",
            body="重启流程",
            tags=[],
            entity_keys=[],
        )
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            filtered = await client.get(
                "/api/admin/bots/assistant1/assistant/memory/search"
                "?query=默认中文&user_id=1001&kinds=semantic&scopes=user"
            )
            assert filtered.status == 200
            filtered_payload = await filtered.json()
            assert [item["id"] for item in filtered_payload["data"]["items"]] == [semantic_id]

            bulk = await client.post(
                "/api/admin/bots/assistant1/assistant/memory/bulk-invalidate",
                json={"memory_ids": [semantic_id, procedural_id, "missing"], "reason": "bulk_web_admin"},
            )
            assert bulk.status == 200
            bulk_payload = await bulk.json()
            assert bulk_payload["data"]["invalidated"] == 2
            assert bulk_payload["data"]["missing"] == ["missing"]

            hidden = await client.get(
                "/api/admin/bots/assistant1/assistant/memory/search?query=默认中文&user_id=1001"
            )
            visible = await client.get(
                "/api/admin/bots/assistant1/assistant/memory/search"
                "?query=默认中文&user_id=1001&include_invalidated=true"
            )
            assert (await hidden.json())["data"]["items"] == []
            assert (await visible.json())["data"]["items"][0]["id"] == semantic_id


@pytest.mark.asyncio
async def test_admin_assistant_proposal_detail_has_files_and_dry_run(
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
    patch_path.write_text(
        "diff --git a/docs/example.md b/docs/example.md\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        "+++ b/docs/example.md\n"
        "@@ -0,0 +1 @@\n"
        "+hello\n",
        encoding="utf-8",
    )

    def fake_run(args, cwd, check, capture_output, text):
        assert args[:3] == ["git", "apply", "--check"]
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("bot.assistant_upgrade_diff.subprocess.run", fake_run)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            detail_resp = await client.get(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}"
            )
            dry_resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/upgrades/{proposal['id']}/dry-run"
            )
            detail = await detail_resp.json()
            dry = await dry_resp.json()
    assert detail["data"]["diff"]["files"][0]["path"] == "docs/example.md"
    assert detail["data"]["diff"]["files"][0]["status"] == "added"
    assert detail["data"]["diff"]["files"][0]["additions"] == 1
    assert dry["data"]["ok"] is True


@pytest.mark.asyncio
async def test_admin_assistant_audit_records_mutations_and_lists_them(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    _enable_local_admin(monkeypatch)
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    _add_assistant_profile(web_manager, workdir)
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="audit proposal", body="body")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            approve_resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}/approve"
            )
            assert approve_resp.status == 200
            audit_resp = await client.get("/api/admin/bots/assistant1/assistant/audit?limit=20")
            assert audit_resp.status == 200
            payload = await audit_resp.json()

    item = payload["data"]["items"][0]
    assert item["action"] == "assistant.proposal.approve"
    assert item["target"]["bot_alias"] == "assistant1"
    assert item["target"]["resource_id"] == proposal["id"]
    assert item["ok"] is True
    assert item["status_code"] == 200
