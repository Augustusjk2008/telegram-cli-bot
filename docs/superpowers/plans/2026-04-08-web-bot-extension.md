# Web Bot Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 Telegram CLI Bridge 扩展为可在手机竖屏上安全访问的 Web Bot，同时保留 Telegram 侧能力，并通过 Cloudflared named tunnel 对外提供稳定访问入口。

**Architecture:** 后端继续复用现有 `MultiBotManager`、session store、`bot/web/server.py` 和 `bot/web/api_service.py`，把 Web 能力作为与 Telegram 并行的第二入口。前端新增一个独立的移动优先 SPA，源码放在 `front/`，构建产物输出到 `front/dist` 由 `aiohttp` 统一托管。公网访问统一走 Cloudflared named tunnel，并在 Cloudflare Access 与应用内 cookie 会话两层做认证；旧 `webcli/ngrok` 路径只保留兼容，不再扩展。

**Tech Stack:** Python 3.12, `aiohttp`, `python-telegram-bot`, React 18, TypeScript, Vite, CSS variables, `cloudflared`, `pytest`, `vitest`, `playwright`.

---

## Scope

- 复用现有 CLI 会话、Bot 管理、文件访问和历史记录逻辑，为 Web 提供一套安全收敛后的接口
- 实现手机竖屏优先的 Web UI，核心场景是选 Bot、聊天、看输出、查看目录、上传下载、重置/终止任务
- 实现 Cloudflared named tunnel 的启动、配置、运维文档和健康检查
- 保留 Telegram 入口；Web 只是第二个入口，不替代 Telegram

## Non-Goals

- 不继续扩写旧的 `bot/handlers/webcli.py`、`bot/handlers/kimi_web.py`、`bot/handlers/combined_server.py`、`bot/handlers/tui_server.py`
- 不做桌面优先复杂布局；桌面端只要求可用，不追求多栏后台
- 不把整个 Windows 桌面暴露到公网；Web 侧默认不开放原始 shell

## Current Codebase Realities

- `bot/web/server.py` 已有 REST API 骨架，并假定静态资源位于 `front/dist`
- `bot/web/api_service.py` 已封装会话、聊天、文件、记忆、管理接口，可复用为服务层
- `bot/main.py` 目前不会启动 `WebApiServer`
- `bot/config.py` 当前把 `WEB_ENABLED` 等配置写死为禁用
- 仓库里没有 `front/` 源码目录，只有历史 `bot/data/webcli/index.html`
- 旧 `webcli/ngrok` 代码存在，但现在已经不是推荐路径

## File Structure

- Modify: `bot/config.py`
  责任：读取 Web 开关、域名、cookie、Cloudflared、目录限制等环境变量
- Create: `bot/runtime_services.py`
  责任：统一启动/停止 Telegram 外围服务，避免 `bot/main.py` 继续膨胀
- Modify: `bot/main.py`
  责任：在同一进程里启动 `WebApiServer`，并把它接入现有生命周期
- Create: `bot/web/auth.py`
  责任：登录口令校验、cookie 签发、cookie 校验、登出
- Create: `bot/web/policy.py`
  责任：Web 侧功能开关、允许访问的工作目录根、危险操作策略
- Modify: `bot/web/server.py`
  责任：新增登录/登出、SSE 聊天、静态资源托管、仅 Web 所需的中间件
- Modify: `bot/web/api_service.py`
  责任：在现有服务层上接入策略校验、共享聊天流式输出、友好错误
- Create: `tests/test_runtime_services.py`
  责任：验证 Web 服务随主进程启停
- Create: `tests/test_web_auth.py`
  责任：验证登录、cookie、未授权访问和登出
- Create: `tests/test_web_policy.py`
  责任：验证目录限制、exec 禁用、管理接口限制
- Create: `tests/test_web_streaming.py`
  责任：验证 SSE 聊天的 `chunk/done/error` 事件
- Create: `front/package.json`
  责任：前端依赖与脚本
- Create: `front/vite.config.ts`
  责任：构建 `front/dist`，开发时代理 `/api`
- Create: `front/src/main.tsx`
  责任：入口
- Create: `front/src/app/App.tsx`
  责任：路由与应用外壳
- Create: `front/src/app/api/client.ts`
  责任：统一调用 REST/SSE、处理 401/403/409
- Create: `front/src/styles/tokens.css`
  责任：颜色、字体、间距、圆角、阴影、动画 token
- Create: `front/src/screens/LoginScreen.tsx`
  责任：移动端登录
- Create: `front/src/screens/BotListScreen.tsx`
  责任：Bot 列表与状态
- Create: `front/src/screens/ChatScreen.tsx`
  责任：主聊天界面，底部输入框固定，支持流式输出
- Create: `front/src/screens/FilesScreen.tsx`
  责任：目录浏览、切目录、上传下载
- Create: `front/src/screens/SettingsScreen.tsx`
  责任：当前 Bot 配置、会话重置、终止任务、管理入口
- Create: `ops/cloudflared/config.template.yml`
  责任：named tunnel 配置模板
- Create: `scripts/cloudflared/start_tunnel.ps1`
  责任：本机启动 named tunnel
- Create: `scripts/cloudflared/install_service.ps1`
  责任：把 tunnel 注册为 Windows 服务
- Create: `docs/web-bot-runbook.md`
  责任：部署、回滚、故障排查、Cloudflare Access 配置

## Product Requirements

- 手机竖屏优先，最低验证视口：`360x800` 和 `390x844`
- 单列布局，不允许横向滚动
- 聊天输入框固定底部，支持安全区
- 常用操作在 1~2 次点击内完成：选 Bot、发消息、停止、重置、切目录
- 视觉上避免“默认模板感”：暖灰背景、深墨文字、强调色使用青绿或铜橙，不使用紫白默认组合
- 安全默认值：
  - 未登录不可访问任何业务 API
  - 默认关闭 `/exec`
  - 默认关闭 Web 管理接口
  - Web 访问目录必须被限制在允许根目录内
  - 公网访问只走 Cloudflared named tunnel，不走 ngrok

## Acceptance Criteria

- `WEB_ENABLED=true` 时，`python -m bot` 同时启动 Telegram 与 Web
- 手机浏览器能在竖屏下完成登录、选 Bot、发消息、终止任务、查看文件
- Web 聊天支持流式输出；Codex/Kimi/Claude 会话可续接
- Web 侧切目录后，会话 id 与 Telegram 侧语义一致地清空
- 未启用的危险功能在 UI 与 API 两侧都不可用
- Cloudflared named tunnel 能把 `https://<hostname>` 转发到本地 `http://127.0.0.1:8765`
- `python -m pytest tests -q` 通过
- `npm run test` 与 `npm run e2e` 通过
- `npm run build` 产出可由 `bot/web/server.py` 正常托管的 `front/dist`

### Task 1: Enable Web Runtime and Configuration

**Files:**
- Modify: `bot/config.py`
- Create: `bot/runtime_services.py`
- Modify: `bot/main.py`
- Test: `tests/test_runtime_services.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_runtime_services.py
import pytest
from unittest.mock import AsyncMock

from bot.models import BotProfile
from bot.manager import MultiBotManager
from bot.runtime_services import RuntimeServices


@pytest.mark.asyncio
async def test_runtime_services_start_and_stop_web_server(tmp_path):
    profile = BotProfile(
        alias="main",
        token="token",
        cli_type="kimi",
        cli_path="kimi",
        working_dir=str(tmp_path),
        enabled=True,
    )
    manager = MultiBotManager(profile, str(tmp_path / "managed_bots.json"))
    web_server = AsyncMock()

    services = RuntimeServices(manager=manager, web_server=web_server, web_enabled=True)
    await services.start()
    await services.stop()

    web_server.start.assert_awaited_once()
    web_server.stop.assert_awaited_once()
```

```python
# tests/test_config.py
def test_web_config_reads_environment(monkeypatch):
    monkeypatch.setenv("WEB_ENABLED", "true")
    monkeypatch.setenv("WEB_PORT", "8765")
    monkeypatch.setenv("WEB_ALLOWED_ROOTS", r"C:\work,C:\repo")

    import importlib
    import bot.config as config

    importlib.reload(config)

    assert config.WEB_ENABLED is True
    assert config.WEB_PORT == 8765
    assert config.WEB_ALLOWED_ROOTS == [r"C:\work", r"C:\repo"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_runtime_services.py tests/test_config.py -q`
Expected: FAIL because `RuntimeServices` and `WEB_ALLOWED_ROOTS` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# bot/runtime_services.py
from dataclasses import dataclass

from bot.web import WebApiServer


@dataclass
class RuntimeServices:
    manager: object
    web_server: WebApiServer | None
    web_enabled: bool

    async def start(self) -> None:
        if self.web_enabled and self.web_server is not None:
            await self.web_server.start()

    async def stop(self) -> None:
        if self.web_enabled and self.web_server is not None:
            await self.web_server.stop()
```

```python
# bot/config.py
WEB_ENABLED = os.environ.get("WEB_ENABLED", "false").lower() == "true"
WEB_HOST = os.environ.get("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEB_PORT = int(os.environ.get("WEB_PORT", "8765"))
WEB_ALLOWED_ROOTS = [
    os.path.abspath(os.path.expanduser(item.strip()))
    for item in os.environ.get("WEB_ALLOWED_ROOTS", WORKING_DIR).split(",")
    if item.strip()
]
```

```python
# bot/main.py
from bot.runtime_services import RuntimeServices
from bot.web import WebApiServer

services = RuntimeServices(
    manager=manager,
    web_server=WebApiServer(manager),
    web_enabled=config.WEB_ENABLED,
)
await services.start()
...
await services.stop()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_runtime_services.py tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/config.py bot/runtime_services.py bot/main.py tests/test_runtime_services.py tests/test_config.py
git commit -m "feat: enable optional web runtime"
```

### Task 2: Add Web Session Login and Cookie Authentication

**Files:**
- Create: `bot/web/auth.py`
- Modify: `bot/web/server.py`
- Test: `tests/test_web_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_auth.py
import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.web.auth import issue_session_cookie
from bot.web.server import WebApiServer


@pytest.mark.asyncio
async def test_login_sets_session_cookie(web_manager, monkeypatch):
    monkeypatch.setattr("bot.web.server.WEB_LOGIN_PASSWORD", "123456")
    monkeypatch.setattr("bot.web.server.WEB_SESSION_SECRET", "secret")
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post("/api/auth/login", json={"password": "123456", "user_id": 1001})
            assert resp.status == 200
            assert "web_session=" in resp.headers.get("Set-Cookie", "")


@pytest.mark.asyncio
async def test_auth_me_accepts_cookie_session(web_manager, monkeypatch):
    monkeypatch.setattr("bot.web.server.WEB_SESSION_SECRET", "secret")
    cookie = issue_session_cookie(user_id=1001, secret="secret")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/api/auth/me", headers={"Cookie": f"web_session={cookie}"})
            assert resp.status == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_auth.py -q`
Expected: FAIL because `/api/auth/login` and cookie auth do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# bot/web/auth.py
import base64
import hashlib
import hmac
import json
import time


def issue_session_cookie(user_id: int, secret: str, ttl_seconds: int = 86400) -> str:
    payload = json.dumps(
        {"user_id": user_id, "exp": int(time.time()) + ttl_seconds},
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_session_cookie(token: str, secret: str) -> int | None:
    body, _, signature = token.partition(".")
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if payload["exp"] < int(time.time()):
        return None
    return int(payload["user_id"])
```

```python
# bot/web/server.py
from .auth import issue_session_cookie, verify_session_cookie

app.router.add_post("/api/auth/login", self.auth_login)
app.router.add_post("/api/auth/logout", self.auth_logout)

async def auth_login(self, request):
    body = await self._parse_json(request)
    if body.get("password") != WEB_LOGIN_PASSWORD:
        raise WebApiError(401, "invalid_password", "口令错误")
    user_id = int(body.get("user_id") or WEB_DEFAULT_USER_ID)
    token = issue_session_cookie(user_id=user_id, secret=WEB_SESSION_SECRET, ttl_seconds=WEB_SESSION_TTL)
    response = _json({"ok": True, "data": {"user_id": user_id}})
    response.set_cookie("web_session", token, httponly=True, samesite="Lax", secure=WEB_COOKIE_SECURE)
    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_auth.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/web/auth.py bot/web/server.py tests/test_web_auth.py
git commit -m "feat: add cookie auth for web bot"
```

### Task 3: Enforce Web Safety Policy and Capability Gating

**Files:**
- Create: `bot/web/policy.py`
- Modify: `bot/config.py`
- Modify: `bot/web/api_service.py`
- Modify: `bot/web/server.py`
- Test: `tests/test_web_policy.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_policy.py
import pytest

from bot.web.api_service import WebApiError, change_working_directory, execute_shell_command


def test_change_working_directory_rejects_path_outside_allowed_roots(web_manager, monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    blocked = tmp_path / "blocked"
    allowed.mkdir()
    blocked.mkdir()
    monkeypatch.setattr("bot.web.api_service.WEB_ALLOWED_ROOTS", [str(allowed)])

    with pytest.raises(WebApiError) as exc_info:
        change_working_directory(web_manager, "main", 1001, str(blocked))

    assert exc_info.value.code == "workdir_not_allowed"


@pytest.mark.asyncio
async def test_exec_is_disabled_by_default(web_manager, monkeypatch):
    monkeypatch.setattr("bot.web.api_service.WEB_ENABLE_EXEC", False)

    with pytest.raises(WebApiError) as exc_info:
        await execute_shell_command(web_manager, "main", 1001, "dir")

    assert exc_info.value.code == "exec_disabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_policy.py -q`
Expected: FAIL because Web policy gating does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# bot/web/policy.py
import os


def is_path_under_allowed_roots(path: str, allowed_roots: list[str]) -> bool:
    real_path = os.path.abspath(path)
    for root in allowed_roots:
        real_root = os.path.abspath(root)
        try:
            if os.path.commonpath([real_root, real_path]) == real_root:
                return True
        except ValueError:
            continue
    return False
```

```python
# bot/web/api_service.py
from bot.config import WEB_ALLOWED_ROOTS, WEB_ENABLE_ADMIN, WEB_ENABLE_EXEC
from bot.web.policy import is_path_under_allowed_roots

if not is_path_under_allowed_roots(path, WEB_ALLOWED_ROOTS):
    _raise(403, "workdir_not_allowed", f"目录不在允许范围内: {path}")

if not WEB_ENABLE_EXEC:
    _raise(403, "exec_disabled", "Web 端默认禁用 Shell 执行")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_policy.py tests/test_web_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/config.py bot/web/policy.py bot/web/api_service.py bot/web/server.py tests/test_web_policy.py tests/test_web_api.py
git commit -m "feat: add web safety policy"
```

### Task 4: Add Streaming Chat Endpoint for Mobile UX

**Files:**
- Create: `bot/web/chat_stream.py`
- Modify: `bot/web/api_service.py`
- Modify: `bot/web/server.py`
- Test: `tests/test_web_streaming.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_streaming.py
import pytest
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import AsyncMock, patch

from bot.web.server import WebApiServer


@pytest.mark.asyncio
async def test_chat_stream_returns_sse_events(web_manager, monkeypatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            with patch(
                "bot.web.server.stream_chat",
                new=AsyncMock(return_value=[
                    {"type": "chunk", "text": "hello"},
                    {"type": "done", "returncode": 0},
                ]),
            ):
                resp = await client.post("/api/bots/main/chat/stream", json={"message": "hi"})
                text = await resp.text()
                assert "event: chunk" in text
                assert "event: done" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_streaming.py -q`
Expected: FAIL because SSE endpoint does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# bot/web/chat_stream.py
import json
from aiohttp import web


async def write_sse(response: web.StreamResponse, event: str, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    await response.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
```

```python
# bot/web/server.py
from .chat_stream import write_sse

app.router.add_post("/api/bots/{alias}/chat/stream", self.post_chat_stream)

async def post_chat_stream(self, request):
    auth = await self._with_auth(request)
    alias = self._manager_alias(request)
    body = await self._parse_json(request)

    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
    )
    await response.prepare(request)

    for item in await stream_chat(self.manager, alias, auth.user_id, body.get("message", "")):
        await write_sse(response, item["type"], item)

    await response.write_eof()
    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_streaming.py tests/test_web_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/web/chat_stream.py bot/web/api_service.py bot/web/server.py tests/test_web_streaming.py
git commit -m "feat: add streaming web chat"
```

### Task 5: Scaffold the Mobile-First Frontend Shell

**Files:**
- Create: `front/package.json`
- Create: `front/tsconfig.json`
- Create: `front/vite.config.ts`
- Create: `front/index.html`
- Create: `front/src/main.tsx`
- Create: `front/src/app/App.tsx`
- Create: `front/src/styles/tokens.css`
- Create: `front/src/styles/global.css`
- Create: `front/src/screens/LoginScreen.tsx`
- Create: `front/src/screens/BotListScreen.tsx`
- Create: `front/src/components/BottomNav.tsx`
- Test: `front/src/test/app.test.tsx`

- [ ] **Step 1: Write the failing frontend test**

```tsx
// front/src/test/app.test.tsx
import { render, screen } from "@testing-library/react";
import { App } from "../app/App";

test("shows mobile login shell when unauthenticated", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Web Bot" })).toBeInTheDocument();
  expect(screen.getByLabelText("访问口令")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- app.test.tsx`
Expected: FAIL because the frontend project does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```json
// front/package.json
{
  "name": "telegram-cli-bridge-web",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run",
    "e2e": "playwright test"
  }
}
```

```tsx
// front/src/app/App.tsx
import "../styles/tokens.css";
import "../styles/global.css";
import { LoginScreen } from "../screens/LoginScreen";

export function App() {
  return <LoginScreen />;
}
```

```css
/* front/src/styles/tokens.css */
:root {
  --bg: #f4efe7;
  --surface: rgba(255, 252, 247, 0.88);
  --text: #1d1b18;
  --muted: #6b645c;
  --accent: #0d8f7a;
  --danger: #b44a2b;
  --radius-xl: 24px;
  --shadow-card: 0 18px 40px rgba(26, 20, 12, 0.12);
  --font-sans: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
```

- [ ] **Step 4: Run tests and build**

Run: `npm install`
Expected: installs frontend dependencies

Run: `npm run test -- app.test.tsx`
Expected: PASS

Run: `npm run build`
Expected: emits `front/dist/index.html`

- [ ] **Step 5: Commit**

```bash
git add front/package.json front/tsconfig.json front/vite.config.ts front/index.html front/src
git commit -m "feat: scaffold mobile web frontend"
```

### Task 6: Implement Core Mobile Screens and Safe Actions

**Files:**
- Create: `front/src/app/api/client.ts`
- Create: `front/src/hooks/useBots.ts`
- Create: `front/src/hooks/useChatStream.ts`
- Modify: `front/src/app/App.tsx`
- Create: `front/src/screens/ChatScreen.tsx`
- Create: `front/src/screens/FilesScreen.tsx`
- Create: `front/src/screens/SettingsScreen.tsx`
- Create: `front/src/components/ChatComposer.tsx`
- Create: `front/src/components/MessageBubble.tsx`
- Create: `front/src/components/FileList.tsx`
- Create: `front/src/components/BotSwitcherSheet.tsx`
- Test: `front/src/test/chat-screen.test.tsx`
- Test: `front/src/test/mobile-layout.spec.ts`

- [ ] **Step 1: Write the failing tests**

```tsx
// front/src/test/chat-screen.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatScreen } from "../screens/ChatScreen";

test("sends message and shows streaming assistant text", async () => {
  render(<ChatScreen botAlias="main" />);
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "hello");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("正在连接")).toBeInTheDocument();
});
```

```ts
// front/src/test/mobile-layout.spec.ts
import { test, expect } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

test("chat page has no horizontal scroll on mobile", async ({ page }) => {
  await page.goto("/");
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const innerWidth = await page.evaluate(() => window.innerWidth);
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- chat-screen.test.tsx`
Expected: FAIL because chat screen and API hooks do not exist.

Run: `npm run e2e -- mobile-layout.spec.ts`
Expected: FAIL because no app routes exist.

- [ ] **Step 3: Write minimal implementation**

```tsx
// front/src/screens/ChatScreen.tsx
export function ChatScreen({ botAlias }: { botAlias: string }) {
  return (
    <main className="screen">
      <header className="screen-header">
        <h1>{botAlias}</h1>
      </header>
      <section className="messages" aria-live="polite" />
      <form className="composer">
        <textarea placeholder="输入消息" rows={1} />
        <button type="submit">发送</button>
      </form>
    </main>
  );
}
```

```ts
// front/src/app/api/client.ts
export async function login(password: string, userId: number) {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ password, user_id: userId }),
  });
  if (!response.ok) throw new Error("login_failed");
  return response.json();
}
```

```tsx
// front/src/app/App.tsx
export function App() {
  return (
    <div className="app-shell">
      <ChatScreen botAlias="main" />
      <BottomNav />
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- chat-screen.test.tsx`
Expected: PASS

Run: `npm run e2e -- mobile-layout.spec.ts`
Expected: PASS on mobile viewport

- [ ] **Step 5: Commit**

```bash
git add front/src/app front/src/hooks front/src/screens front/src/components front/src/test
git commit -m "feat: implement mobile chat and tools screens"
```

### Task 7: Add Cloudflared Named Tunnel Tooling and Runbook

**Files:**
- Create: `ops/cloudflared/config.template.yml`
- Create: `scripts/cloudflared/start_tunnel.ps1`
- Create: `scripts/cloudflared/install_service.ps1`
- Create: `docs/web-bot-runbook.md`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
def test_cloudflared_config_values(monkeypatch):
    monkeypatch.setenv("CLOUDFLARED_TUNNEL_NAME", "telegram-cli-bridge")
    monkeypatch.setenv("CLOUDFLARED_HOSTNAME", "bot.example.com")

    import importlib
    import bot.config as config

    importlib.reload(config)

    assert config.CLOUDFLARED_TUNNEL_NAME == "telegram-cli-bridge"
    assert config.CLOUDFLARED_HOSTNAME == "bot.example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL because the Cloudflared config keys do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# bot/config.py
CLOUDFLARED_TUNNEL_NAME = os.environ.get("CLOUDFLARED_TUNNEL_NAME", "telegram-cli-bridge").strip()
CLOUDFLARED_HOSTNAME = os.environ.get("CLOUDFLARED_HOSTNAME", "").strip()
```

```yaml
# ops/cloudflared/config.template.yml
tunnel: YOUR_TUNNEL_UUID
credentials-file: C:\cloudflared\YOUR_TUNNEL_UUID.json

ingress:
  - hostname: bot.example.com
    service: http://127.0.0.1:8765
  - service: http_status:404
```

```powershell
# scripts/cloudflared/start_tunnel.ps1
param(
    [string]$ConfigPath = ".\\ops\\cloudflared\\config.yml"
)

cloudflared tunnel --config $ConfigPath run
```

- [ ] **Step 4: Run verification**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS

Run: `cloudflared tunnel ingress validate --config .\ops\cloudflared\config.yml`
Expected: `Valid configuration`

- [ ] **Step 5: Commit**

```bash
git add bot/config.py ops/cloudflared/config.template.yml scripts/cloudflared/start_tunnel.ps1 scripts/cloudflared/install_service.ps1 docs/web-bot-runbook.md tests/test_config.py
git commit -m "feat: add cloudflared deployment tooling"
```

### Task 8: Final QA, Legacy Freeze, and Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `REVIEW.md`
- Modify: `bot/data/README.md`
- Modify: `AGENTS.md`
- Create: `docs/web-bot-checklist.md`
- Test: `tests/test_web_api.py`
- Test: `front/src/test/mobile-layout.spec.ts`

- [ ] **Step 1: Write the failing acceptance checklist**

```markdown
# docs/web-bot-checklist.md

- [ ] iPhone 12 viewport can login
- [ ] Bot list loads in under 2 seconds on LAN
- [ ] Chat stream receives `chunk` then `done`
- [ ] `/exec` hidden when `WEB_ENABLE_EXEC=false`
- [ ] Files tab cannot leave allowed roots
- [ ] cloudflared named tunnel returns 200 from `/api/health`
```

- [ ] **Step 2: Run the full verification set before cleanup**

Run: `python -m pytest tests -q`
Expected: PASS

Run: `npm run test`
Expected: PASS

Run: `npm run e2e`
Expected: PASS

- [ ] **Step 3: Freeze legacy paths and update docs**

```python
# bot/handlers/webcli.py
raise RuntimeError("legacy webcli path is deprecated; use bot/web/server.py + front/dist")
```

```markdown
# CLAUDE.md
- Legacy `bot/handlers/webcli.py` and `bot/handlers/kimi_web.py` are frozen compatibility code.
- Active Web implementation lives in `bot/web/*` and `front/*`.
```

```markdown
# docs/web-bot-checklist.md
- Capture screenshots on iPhone Safari and Android Chrome
- Verify Cloudflare Access policy before sharing link
- Verify cookie logout clears `web_session`
```

- [ ] **Step 4: Run the final verification after docs and freeze**

Run: `python -m pytest tests -q`
Expected: PASS

Run: `npm run build`
Expected: PASS and `front/dist` updated

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md REVIEW.md bot/data/README.md AGENTS.md docs/web-bot-checklist.md bot/handlers/webcli.py
git commit -m "docs: finalize web bot rollout checklist"
```

## Risk Register

- `bot/web/api_service.py` 现在把文件和 Shell 能力都暴露出来；如果不先做策略层，Web 入口上线就是高风险
- 如果继续依赖旧 `webcli/ngrok`，代码会分裂成两套 Web 体系，维护成本会继续上升
- 如果前端不做流式输出，移动端会误以为请求卡死，体验会明显差于 Telegram
- 如果 tunnel 只用 quick tunnel 而不加 Access，公网链接泄露后几乎等于裸露接口
- 如果直接把 `WORKING_DIR` 暴露成任意可切换目录，误删或越权访问风险很高

## Rollout Notes

- 开发环境可以先用 `cloudflared tunnel --url http://127.0.0.1:8765` 做临时联调，但生产必须切 named tunnel
- Web 入口默认只给主用户；多用户能力需要在 `AuthContext` 和 session 隔离上重新评审
- 先完成 Task 1-4 再做前端，不要在后端契约未稳定前提前铺开 UI

## Self-Review

- 覆盖性：运行时、认证、安全策略、移动端 UI、Cloudflared、文档与验收都已对应到独立任务
- 无占位词：所有任务都给了具体文件、测试、命令和示例代码
- 一致性：主动 Web 方案统一指向 `bot/web/* + front/* + cloudflared`，没有再把旧 `webcli/ngrok` 当成目标实现
