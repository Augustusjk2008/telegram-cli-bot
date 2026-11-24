from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import git_service
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_GIT_OPS
from bot.web.server import WebApiServer


def _repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(("args", "read_only"), [
    (["status", "--porcelain=v2"], True),
    (["log", "-1"], True),
    (["config", "--global", "--get", "user.name"], True),
    (["config", "--global", "user.name", "x"], False),
    (["symbolic-ref", "--quiet", "--short", "HEAD"], True),
    (["symbolic-ref", "HEAD", "refs/heads/x"], False),
    (["remote", "-v"], True),
    (["remote", "add", "--", "o", "u"], False),
    (["stash", "list"], True),
    (["stash", "pop"], False),
    (["push"], False),
    (["branch", "x"], False),
])
def test_only_read_only_git_commands_skip_the_mutation_lock(args, read_only):
    assert git_service._git_command_is_read_only(args) is read_only


def test_reads_do_not_wait_for_a_mutation_holding_the_repo_lock(tmp_path):
    repo = _repo(tmp_path / "repo")
    held, release = threading.Event(), threading.Event()

    def long_sync() -> None:
        with git_service._git_repo_lock(repo):
            held.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=3) as pool:
        holder = pool.submit(long_sync)
        assert held.wait(5)
        try:
            snapshot = pool.submit(git_service._build_repo_status_snapshot, repo).result(timeout=5)
            assert snapshot
            assert pool.submit(git_service._run_git, repo, ["log", "-1", "--format=%s"]).result(timeout=5).stdout.strip() == "init"
            write = pool.submit(git_service._run_git, repo, ["add", "a.txt"])
            time.sleep(0.2)
            assert not write.done()
        finally:
            release.set()
        holder.result(timeout=5)
        write.result(timeout=5)


class _Backend:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.commit_error: WebApiError | None = None

    def push(self):
        assert self.release.wait(10)
        return {"repo_found": True, "ahead_count": 0}

    def fetch(self):
        return {"repo_found": True}

    def commit(self, message):
        if self.commit_error:
            raise self.commit_error
        return {"repo_found": True, "message": message}

    async def generate_commit_message(self):
        return {"message": "feat: generated"}


def _server(tmp_path, monkeypatch):
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(tmp_path)), str(storage))
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(manager, host="127.0.0.1", port=8765)
    auth = AuthContext(user_id=7, token_used=True, account_id="member", capabilities={CAP_GIT_OPS})
    monkeypatch.setattr(server, "_auth_context", lambda request: auth)
    monkeypatch.setattr(server, "_can_operate_bot", lambda auth, alias: alias == "main")
    backend = _Backend()
    calls: list[str] = []

    async def get_backend(alias, user_id, *, account_id=""):
        calls.append(account_id)
        return backend

    monkeypatch.setattr(server, "_get_git_backend", get_backend)
    return server, SimpleNamespace(backend=backend, account_ids=calls)


async def _finished(client, operation_id: str) -> dict:
    for _ in range(100):
        response = await client.get(f"/api/bots/main/git/operations/{operation_id}")
        assert response.status == 200, await response.text()
        data = (await response.json())["data"]
        if data["status"] != "running":
            return data
        await asyncio.sleep(0.05)
    raise AssertionError("operation did not finish")


@pytest.mark.asyncio
async def test_started_operation_keeps_running_and_reports_its_result(tmp_path, monkeypatch):
    server, state = _server(tmp_path, monkeypatch)
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.post("/api/bots/main/git/operations", json={"kind": "push"})
        assert response.status == 200, await response.text()
        started = (await response.json())["data"]
        assert started["kind"] == "push" and started["status"] == "running"
        assert state.account_ids == ["member"]

        # A page opened later finds the same operation, and cannot start another one.
        active = (await (await client.get("/api/bots/main/git/operations/active")).json())["data"]
        assert active["operation_id"] == started["operation_id"] and active["status"] == "running"
        busy = await client.post("/api/bots/main/git/operations", json={"kind": "fetch"})
        assert busy.status == 409
        assert (await busy.json())["error"]["code"] == "git_operation_running"

        state.backend.release.set()
        finished = await _finished(client, started["operation_id"])
        assert finished["status"] == "succeeded"
        assert finished["notice"] == "已推送本地提交"
        assert finished["overview"] == {"repo_found": True, "ahead_count": 0}
        assert finished["error"] is None and finished["finished_at"] >= finished["started_at"]

        generated = (await (await client.post(
            "/api/bots/main/git/operations", json={"kind": "commit_message"},
        )).json())["data"]
        assert (await _finished(client, generated["operation_id"]))["commit_message"] == "feat: generated"
        # Only the latest operation is kept.
        missing = await client.get(f"/api/bots/main/git/operations/{started['operation_id']}")
        assert missing.status == 404


@pytest.mark.asyncio
async def test_failed_operation_keeps_the_api_error(tmp_path, monkeypatch):
    server, state = _server(tmp_path, monkeypatch)
    state.backend.commit_error = WebApiError(400, "git_commit_failed", "hook rejected", {"outcome": "failed"})
    async with TestClient(TestServer(server._build_app())) as client:
        invalid = await client.post("/api/bots/main/git/operations", json={"kind": "reset --hard"})
        assert invalid.status == 400
        assert (await invalid.json())["error"]["code"] == "invalid_git_operation"

        started = (await (await client.post(
            "/api/bots/main/git/operations", json={"kind": "commit", "message": "x"},
        )).json())["data"]
        failed = await _finished(client, started["operation_id"])
        assert failed["status"] == "failed"
        assert failed["error"] == {
            "status": 400, "code": "git_commit_failed", "message": "hook rejected", "data": {"outcome": "failed"},
        }
        # Commits do not receive the account's GitHub credentials.
        assert state.account_ids == [""]

        # The synchronous endpoints keep their response shape.
        state.backend.release.set()
        response = await client.post("/api/bots/main/git/push", json={})
        assert (await response.json())["data"] == {"message": "已推送本地提交", "overview": {"repo_found": True, "ahead_count": 0}}
