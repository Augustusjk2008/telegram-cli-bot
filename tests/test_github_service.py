from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import git_service as local_git
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_GIT_OPS, CAP_VIEW_FILE_TREE
from bot.web.github_service import (
    GITHUB_DEVICE_CODE_URL,
    GITHUB_OAUTH_TOKEN_URL,
    GitHubCredential,
    GitHubCredentialStore,
    GitHubResponse,
    GitHubService,
    build_github_git_auth_config,
)
from bot.web.server import WebApiServer


TOKEN = "ghp_" + "A1b2C3d4E5" * 3 + "xyzxyz"
OAUTH_TOKEN = "gho_" + "Z9y8X7w6V5" * 3 + "abcabc"


class FakeGitHub:
    """Records GitHub requests and replays queued responses per URL suffix."""

    def __init__(self):
        self.requests: list[dict] = []
        self.responses: dict[str, list[GitHubResponse]] = {}

    def queue(self, key: str, status: int, data, headers=None):
        self.responses.setdefault(key, []).append(GitHubResponse(status, data, headers or {}))

    async def __call__(self, method, url, *, headers, json_body=None, form=None, params=None):
        self.requests.append({"method": method, "url": url, "headers": dict(headers), "json": json_body, "form": form, "params": params})
        for key, queued in self.responses.items():
            if url.endswith(key) and queued:
                return queued.pop(0) if len(queued) > 1 else queued[0]
        raise AssertionError(f"unexpected GitHub request {method} {url}")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _user(login="octocat"):
    return {"login": login, "id": 7, "name": "Mona", "avatar_url": "https://avatars.example/7", "html_url": f"https://github.com/{login}"}


def _service(tmp_path, *, client_id="Iv1.client", clock=None):
    fake = FakeGitHub()
    service = GitHubService(
        GitHubCredentialStore(tmp_path / "github"),
        fake,
        clock=clock or Clock(),
        client_id_provider=lambda: client_id,
    )
    return service, fake


def test_credential_store_encrypts_tokens_and_isolates_accounts(tmp_path):
    store = GitHubCredentialStore(tmp_path / "github")
    store.save("member-a", GitHubCredential(token=TOKEN, login="octocat", scopes=("repo",)))

    files = list((tmp_path / "github" / "accounts").glob("*.json"))
    assert len(files) == 1
    assert TOKEN not in files[0].read_text(encoding="utf-8")
    assert "member-a" not in files[0].name
    if os.name != "nt":
        assert files[0].stat().st_mode & 0o077 == 0
        assert (tmp_path / "github" / "secret.key").stat().st_mode & 0o077 == 0
    assert store.get("member-a").token == TOKEN
    assert store.get("member-b") is None

    payload = json.loads(files[0].read_text(encoding="utf-8"))
    payload["token_enc"] = payload["token_enc"][:-4] + "AAAA"
    files[0].write_text(json.dumps(payload), encoding="utf-8")
    assert store.get("member-a") is None
    assert store.delete("member-a") is True
    assert store.get("member-a") is None


@pytest.mark.asyncio
async def test_token_connection_validates_with_github_and_never_returns_the_token(tmp_path):
    service, fake = _service(tmp_path)
    fake.queue("/user", 200, _user(), {"x-oauth-scopes": "repo, read:org"})

    status = await service.connect_with_token("member-a", f"  {TOKEN}\n")

    assert status["connected"] is True
    assert (status["login"], status["auth_method"], status["token_kind"]) == ("octocat", "token", "classic")
    assert status["scopes"] == ["repo", "read:org"]
    assert TOKEN not in json.dumps(status)
    assert fake.requests[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in json.dumps(await service.account_status("member-a"))
    assert (await service.account_status("member-b"))["connected"] is False

    disconnected = await service.disconnect("member-a")
    assert disconnected["connected"] is False
    assert service.store.get("member-a") is None


@pytest.mark.asyncio
async def test_rejected_or_malformed_tokens_are_not_stored(tmp_path):
    service, fake = _service(tmp_path)
    with pytest.raises(WebApiError) as exc:
        await service.connect_with_token("member-a", "not a token")
    assert exc.value.code == "invalid_github_token"
    assert fake.requests == []

    fake.queue("/user", 401, {"message": "Bad credentials"})
    with pytest.raises(WebApiError) as exc:
        await service.connect_with_token("member-a", TOKEN)
    # 401 is reserved for the Orbit session itself.
    assert (exc.value.status, exc.value.code) == (409, "github_token_invalid")
    assert service.store.get("member-a") is None


@pytest.mark.asyncio
async def test_device_flow_respects_interval_slow_down_and_account_binding(tmp_path):
    clock = Clock()
    service, fake = _service(tmp_path, clock=clock)
    fake.queue(GITHUB_DEVICE_CODE_URL, 200, {
        "device_code": "device-secret",
        "user_code": "ABCD-1234",
        "verification_uri": "https://evil.example/phish",
        "expires_in": 900,
        "interval": 5,
    })

    flow = await service.start_device_flow("member-a")

    assert flow["user_code"] == "ABCD-1234"
    assert flow["verification_uri"] == "https://github.com/login/device"
    assert "device-secret" not in json.dumps(flow)
    assert fake.requests[0]["form"] == {"client_id": "Iv1.client", "scope": "repo read:org"}

    assert (await service.poll_device_flow("member-a", flow["flow_id"]))["status"] == "pending"
    assert len(fake.requests) == 1, "polls inside the interval must not reach GitHub"
    with pytest.raises(WebApiError) as exc:
        await service.poll_device_flow("member-b", flow["flow_id"])
    assert exc.value.code == "github_device_flow_not_found"

    fake.queue(GITHUB_OAUTH_TOKEN_URL, 200, {"error": "slow_down", "interval": 10})
    fake.queue(GITHUB_OAUTH_TOKEN_URL, 200, {"access_token": OAUTH_TOKEN, "scope": "repo,read:org"})
    fake.queue("/user", 200, _user())
    clock.now += 5
    slowed = await service.poll_device_flow("member-a", flow["flow_id"])
    assert (slowed["status"], slowed["interval"]) == ("pending", 10)
    assert fake.requests[-1]["form"]["device_code"] == "device-secret"
    clock.now += 5
    assert (await service.poll_device_flow("member-a", flow["flow_id"]))["status"] == "pending"
    clock.now += 5

    connected = await service.poll_device_flow("member-a", flow["flow_id"])

    assert connected["status"] == "connected"
    assert connected["account"]["auth_method"] == "device"
    assert connected["account"]["scopes"] == ["repo", "read:org"]
    assert OAUTH_TOKEN not in json.dumps(connected)
    assert service.store.get("member-a").token == OAUTH_TOKEN
    with pytest.raises(WebApiError):
        await service.poll_device_flow("member-a", flow["flow_id"])


@pytest.mark.asyncio
async def test_device_flow_requires_a_client_id_and_reports_terminal_states(tmp_path):
    service, fake = _service(tmp_path, client_id="")
    with pytest.raises(WebApiError) as exc:
        await service.start_device_flow("member-a")
    assert exc.value.code == "github_device_flow_unavailable"
    assert (await service.account_status("member-a"))["device_flow_available"] is False

    clock = Clock()
    service, fake = _service(tmp_path, clock=clock)
    fake.queue(GITHUB_DEVICE_CODE_URL, 200, {"device_code": "d", "user_code": "U", "interval": 1})
    flow = await service.start_device_flow("member-a")
    fake.queue(GITHUB_OAUTH_TOKEN_URL, 200, {"error": "access_denied"})
    clock.now += 1
    assert (await service.poll_device_flow("member-a", flow["flow_id"]))["status"] == "denied"

    fake.responses[GITHUB_DEVICE_CODE_URL] = [GitHubResponse(200, {"error": "device_flow_disabled"}, {})]
    with pytest.raises(WebApiError) as exc:
        await service.start_device_flow("member-a")
    assert exc.value.code == "github_device_flow_disabled"


@pytest.mark.asyncio
async def test_repositories_are_listed_and_created_empty_for_user_or_org(tmp_path):
    service, fake = _service(tmp_path)
    service.store.save("member-a", GitHubCredential(token=TOKEN, login="octocat"))
    fake.queue("/user/repos", 200, [{
        "id": 1, "name": "demo", "full_name": "octocat/demo", "owner": {"login": "octocat"},
        "private": True, "clone_url": "https://github.com/octocat/demo.git",
        "ssh_url": "git@github.com:octocat/demo.git", "permissions": {"push": True},
    }], {"link": '<https://api.github.com/user/repos?page=2>; rel="next"'})

    listed = await service.list_repositories("member-a", page="1")

    assert listed["has_more"] is True
    assert listed["items"][0]["full_name"] == "octocat/demo" and listed["items"][0]["can_push"] is True

    fake.responses.clear()
    fake.queue("/user/repos", 201, {"name": "new", "full_name": "octocat/new", "owner": {"login": "octocat"}})
    fake.queue("/orgs/acme/repos", 201, {"name": "tool", "full_name": "acme/tool", "owner": {"login": "acme"}})
    assert (await service.create_repository("member-a", name="new", description="line\nbreak"))["full_name"] == "octocat/new"
    assert fake.requests[-1]["json"] == {"name": "new", "description": "line break", "private": True, "auto_init": False}
    assert (await service.create_repository("member-a", owner="acme", name="tool", private=False))["full_name"] == "acme/tool"
    assert fake.requests[-1]["url"].endswith("/orgs/acme/repos")
    assert fake.requests[-1]["json"]["private"] is False

    request_count = len(fake.requests)
    for name in ("", "bad name", "x.git", ".."):
        with pytest.raises(WebApiError) as exc:
            await service.create_repository("member-a", name=name)
        assert exc.value.code == "invalid_github_repo_name"
    assert len(fake.requests) == request_count

    fake.responses.clear()
    fake.queue("/user/repos", 422, {"message": "Repository creation failed.", "errors": [{"message": "name already exists on this account"}]})
    with pytest.raises(WebApiError) as exc:
        await service.create_repository("member-a", name="new")
    assert exc.value.code == "github_repo_exists"
    with pytest.raises(WebApiError) as exc:
        await service.list_repositories("member-b")
    assert exc.value.code == "github_not_connected"


def test_git_auth_config_only_applies_to_github_https_and_stays_out_of_argv(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    entries = build_github_git_auth_config("octocat", TOKEN)
    env = local_git._build_git_remote_env(str(repo), entries)

    def urlmatch(key, url):
        return subprocess.run(
            ["git", "config", "--get-urlmatch", key, url],
            cwd=repo, env=env, capture_output=True, text=True,
        ).stdout.strip()

    expected = "Authorization: Basic " + base64.b64encode(f"octocat:{TOKEN}".encode()).decode()
    assert urlmatch("http.extraheader", "https://github.com/octocat/demo.git") == expected
    for other in ("https://github.com.evil.example/x", "https://gist.github.com/x", "https://gitlab.com/x"):
        assert urlmatch("http.extraheader", other) == ""
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert all(TOKEN not in part for part in local_git._build_git_command(["push"]))
    assert local_git._build_git_remote_env(str(repo)).get("GIT_TERMINAL_PROMPT") == os.environ.get("GIT_TERMINAL_PROMPT")


def _server(tmp_path, monkeypatch, profile: BotProfile):
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(profile, str(storage))
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(manager, host="127.0.0.1", port=8765)
    auth = AuthContext(user_id=42, token_used=True, account_id="member-a", capabilities={CAP_VIEW_FILE_TREE})
    monkeypatch.setattr(server, "_auth_context", lambda request: auth)
    monkeypatch.setattr(server, "_can_operate_bot", lambda auth, alias: alias == "main")
    service, fake = _service(tmp_path)
    server._github_service = service
    return server, auth, service, fake


@pytest.mark.asyncio
async def test_github_routes_require_git_ops_and_are_scoped_to_the_account(tmp_path, monkeypatch):
    server, auth, service, fake = _server(tmp_path, monkeypatch, BotProfile(alias="main", working_dir=str(tmp_path)))
    fake.queue("/user", 200, _user(), {"x-oauth-scopes": "repo"})
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.get("/api/github/account")
        assert response.status == 403
        auth.capabilities.add(CAP_GIT_OPS)

        response = await client.post("/api/github/account/token", json={"token": TOKEN})
        assert response.status == 200, await response.text()
        assert TOKEN not in await response.text()
        assert (await response.json())["data"]["login"] == "octocat"

        auth.account_id = "member-b"
        response = await client.get("/api/github/account")
        assert (await response.json())["data"]["connected"] is False
        response = await client.get("/api/github/repos")
        assert (response.status, (await response.json())["error"]["code"]) == (409, "github_not_connected")
        response = await client.post("/api/github/repos", json={"name": "demo", "private": "yes"})
        assert response.status == 400

        auth.account_id = "member-a"
        response = await client.delete("/api/github/account")
        assert (await response.json())["data"]["connected"] is False
    assert service.store.get("member-a") is None


@pytest.mark.asyncio
async def test_local_network_git_uses_the_requesters_github_account(tmp_path, monkeypatch):
    server, auth, service, _fake = _server(tmp_path, monkeypatch, BotProfile(alias="main", working_dir=str(tmp_path)))
    auth.capabilities.add(CAP_GIT_OPS)
    service.store.save("member-a", GitHubCredential(token=TOKEN, login="octocat"))
    push = Mock(return_value={"repo_found": True})
    publish = Mock(return_value={"repo_found": True})
    monkeypatch.setattr(local_git, "push_git_remote", push)
    monkeypatch.setattr(local_git, "publish_git_branch", publish)

    async with TestClient(TestServer(server._build_app())) as client:
        assert (await client.post("/api/bots/main/git/push")).status == 200
        assert (await client.post("/api/bots/main/git/publish", json={"remote": "origin"})).status == 200
        auth.account_id = "member-b"
        assert (await client.post("/api/bots/main/git/push")).status == 200

    expected = build_github_git_auth_config("octocat", TOKEN)
    assert push.call_args_list[0].kwargs == {"auth_config": expected}
    assert publish.call_args.args[3] == "origin"
    assert publish.call_args.kwargs == {"auth_config": expected}
    assert push.call_args_list[1].kwargs == {"auth_config": ()}
