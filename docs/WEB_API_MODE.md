# Web API 模式说明

## 目标

在不破坏现有 Telegram Bot 行为的前提下，为项目增加一套 HTTP API，让前端可以通过 Web 方式访问同一套后端能力。

设计原则：

- 保留现有 `sessions`、`MultiBotManager`、CLI 调用、文件能力、记忆能力。
- Telegram 仍可继续使用；Web 只是新增访问面。
- Web API 默认与 Telegram 共享同一套 Bot/Profile 配置。

## 启动方式

环境变量：

```env
TELEGRAM_ENABLED=true
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-me
WEB_ALLOWED_ORIGINS=http://localhost:5173
WEB_DEFAULT_USER_ID=123456789
```

启动：

```bash
python -m bot
```

说明：

- `TELEGRAM_ENABLED=true` 时，维持现有 Telegram 轮询逻辑。
- `WEB_ENABLED=true` 时，同时启动 `aiohttp` Web API。
- 若只想跑 Web，可设 `TELEGRAM_ENABLED=false`、`WEB_ENABLED=true`。

## 鉴权约定

- 若配置了 `WEB_API_TOKEN`，请求需带：
  - `Authorization: Bearer <token>`
  - 或 `X-API-Token: <token>`
- 用户维度通过 `X-User-Id` 指定。
- 若未传 `X-User-Id`，使用 `WEB_DEFAULT_USER_ID`。
- 若配置了 `ALLOWED_USER_IDS`，则 `X-User-Id` 必须在白名单内。

## 已实现接口

### 基础

- `GET /api/health`
- `GET /api/auth/me`

### Bot / 会话

- `GET /api/bots`
- `GET /api/bots/{alias}`
- `POST /api/bots/{alias}/chat`
- `POST /api/bots/{alias}/exec`
- `GET /api/bots/{alias}/pwd`
- `GET /api/bots/{alias}/ls`
- `POST /api/bots/{alias}/cd`
- `POST /api/bots/{alias}/reset`
- `POST /api/bots/{alias}/kill`
- `GET /api/bots/{alias}/history`

### 文件

- `POST /api/bots/{alias}/files/upload`
- `GET /api/bots/{alias}/files/download?filename=...`
- `GET /api/bots/{alias}/files/read?filename=...&mode=cat`
- `GET /api/bots/{alias}/files/read?filename=...&mode=head&lines=20`

### Assistant 记忆

- `GET /api/memory`
- `POST /api/memory`
- `GET /api/memory/search?keyword=...`
- `DELETE /api/memory/{memory_id}`
- `DELETE /api/memory`
- `GET /api/tool-stats`

### 管理能力

- `GET /api/admin/scripts`
- `POST /api/admin/scripts/run`
- `POST /api/admin/bots`
- `GET /api/admin/bots/{alias}`
- `DELETE /api/admin/bots/{alias}`
- `POST /api/admin/bots/{alias}/start`
- `POST /api/admin/bots/{alias}/stop`
- `PATCH /api/admin/bots/{alias}/cli`
- `PATCH /api/admin/bots/{alias}/workdir`
- `GET /api/admin/bots/{alias}/processing`
- `POST /api/admin/restart`

## 返回格式

成功：

```json
{
  "ok": true,
  "data": {}
}
```

失败：

```json
{
  "ok": false,
  "error": {
    "code": "unauthorized",
    "message": "访问令牌无效"
  }
}
```

## 当前边界

- Web API 已覆盖 CLI 聊天、Shell、目录、文件、历史、Assistant 记忆、部分管理能力。
- `bot_mode=webcli` 的 Telegram 专用引导流程未映射为新的 Web 页面工作流；Web 前端应聚焦 `cli` / `assistant` 模式。
- 当前为请求-响应式接口，没有实现消息流式推送；前端应使用“发送后等待完成”的交互。
