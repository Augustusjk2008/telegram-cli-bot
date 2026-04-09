# Web Bot Tunnel And CLI Settings Design

日期：2026-04-09

## 目标

为当前 `bot/web/* + front/` Web Bot 增加两项能力：

1. 接入 Cloudflare Quick Tunnel，让手机可通过公网临时访问当前 Web Bot。
2. 在 Web 设置页直接查看和修改当前 Bot 的 CLI 参数，重点覆盖 `codex` 参数。

## 用户确认的约束

- Tunnel 方案使用 Cloudflare 临时 Quick Tunnel。
- Web 中任何已登录用户都可以修改当前 Bot 的 CLI 参数。
- 前端交互沿用现有设置页，不另外开独立管理页面。

## 现状

- Telegram 管理命令已经支持查看、设置、重置 Bot CLI 参数。
- 当前 Web API 没有暴露 CLI 参数查询和修改接口。
- 当前 Web 设置页只有概览、终止任务、重置会话、退出登录。
- Cloudflare Tunnel 相关代码只存在旧 `kimi_web.py` 路线，当前 `aiohttp` Web 栈没有正式集成。
- `WEB_PUBLIC_URL` 目前只有配置项，没有被当前 Web 服务用于 tunnel 生命周期管理。

## 方案选择

本次采用以下方案：

- 在当前 `aiohttp` Web 服务旁边新增一个轻量 `TunnelService`，只负责临时 `cloudflared tunnel --url ...` 生命周期。
- Web API 新增 tunnel 状态与控制接口。
- Web API 新增按 Bot 维度的 CLI 参数读取、更新、重置接口。
- 前端在现有设置页增加两个区块：
  - CLI 参数设置
  - 公网访问 / Tunnel 状态

不采用独立外部脚本管理 tunnel，也不抽象成多 provider 通用框架。

## 后端设计

### TunnelService

新增 `bot/web/tunnel_service.py`，职责限定为：

- 解析 `cloudflared` 可执行文件路径
- 启动 Quick Tunnel 子进程
- 从输出中提取 `https://*.trycloudflare.com`
- 维护运行状态、最新公网 URL、最后错误
- 提供 `start()` / `stop()` / `restart()` / `snapshot()` 接口

状态模型至少包含：

- `mode`: `disabled` / `cloudflare_quick` / `manual`
- `status`: `stopped` / `starting` / `running` / `error`
- `public_url`
- `local_url`
- `source`: `quick_tunnel` / `manual_config`
- `last_error`
- `pid`

### Web 服务集成

`WebApiServer` 持有 `TunnelService` 实例：

- `start()` 中，Web 服务监听成功后再决定是否自动启动 tunnel
- `stop()` 中统一清理 tunnel 子进程

优先级：

1. 若配置了 `WEB_PUBLIC_URL`，视为手工公网地址，不自动启动 Quick Tunnel
2. 若启用 `WEB_TUNNEL_MODE=cloudflare_quick`，则为 `http://WEB_HOST:WEB_PORT` 自动拉起 Quick Tunnel
3. 其余情况 tunnel 处于 disabled/stopped

### 新配置项

在 `bot/config.py` 增加：

- `WEB_TUNNEL_MODE`
- `WEB_TUNNEL_AUTOSTART`
- `WEB_TUNNEL_CLOUDFLARED_PATH`

建议语义：

- `WEB_TUNNEL_MODE`: `disabled` / `cloudflare_quick`
- `WEB_TUNNEL_AUTOSTART`: 默认 `true`
- `WEB_TUNNEL_CLOUDFLARED_PATH`: 允许显式指定 `cloudflared.exe`

### CLI 参数 API

新增 bot 维度接口：

- `GET /api/bots/{alias}/cli-params`
- `PATCH /api/bots/{alias}/cli-params`
- `POST /api/bots/{alias}/cli-params/reset`

行为：

- 默认返回当前 bot 的 `profile.cli_type` 对应参数
- 允许通过 query/body 指定 `cli_type`
- 更新时只允许单字段 patch：`key + value`
- 重置时支持只重置某个 CLI 类型

为避免前端自行猜类型，接口返回：

- `cli_type`
- `params`
- `schema`
- `defaults`

`schema` 至少描述：

- 字段名
- 字段类型：`boolean` / `string` / `number` / `string_list`
- 可选枚举值
- 说明文字

### Tunnel API

新增全局管理接口：

- `GET /api/admin/tunnel`
- `POST /api/admin/tunnel/start`
- `POST /api/admin/tunnel/stop`
- `POST /api/admin/tunnel/restart`

这些接口继续沿用现有 Web token 认证，不额外引入角色系统。

## 前端设计

### 设置页结构

在现有 [SettingsScreen](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/SettingsScreen.tsx) 内追加两个卡片区块：

1. `CLI 参数`
2. `公网访问`

保持现有危险操作区块不变。

### CLI 参数区块

只展示“当前 bot 当前 CLI 类型”的参数，不做跨 CLI 切换。

控件映射：

- `boolean` -> 开关
- `enum string` -> 下拉
- `plain string` -> 单行输入框
- `number` -> 数字输入框
- `string_list` -> 多值文本框，使用一行一个参数的方式编辑

交互：

- 进入设置页时拉取一次当前值与 schema
- 单字段保存，保存后刷新当前参数
- 提供“恢复默认参数”按钮
- 对 `codex` 重点展示 `reasoning_effort`、`model`、`skip_git_check`、`json_output`、`yolo`、`extra_args`

### 公网访问区块

展示：

- 当前 tunnel 状态
- 公网 URL
- 本地 URL
- 最后错误

操作：

- `启动`
- `停止`
- `重启`
- `复制公网地址`

如果当前来源是 `WEB_PUBLIC_URL` 手工配置，则显示“手工配置地址”，隐藏启动/停止操作，只保留展示。

## 数据流

### CLI 参数

1. 前端进入设置页
2. `RealWebBotClient` 请求 `/api/bots/{alias}/cli-params`
3. 后端读取 `manager.get_bot_cli_params()`
4. 后端附带 schema/defaults 返回
5. 前端按 schema 渲染控件
6. 用户修改某一项时发 `PATCH`
7. 保存成功后刷新当前参数和提示

### Tunnel

1. Web 服务启动后，如果配置允许则自动拉起 Quick Tunnel
2. 前端设置页请求 `/api/admin/tunnel`
3. 用户点击控制按钮时发 `start/stop/restart`
4. 后端返回最新 snapshot
5. 前端刷新卡片显示

## 错误处理

### Tunnel

- `cloudflared` 不存在：返回明确错误，并在状态卡中显示安装/路径问题
- 输出里超时未拿到 URL：状态置为 `error`
- tunnel 进程异常退出：记录 `last_error`，状态置为 `error`
- stop 时如果进程已经退出，不视为失败

### CLI 参数

- 不允许未知 key
- 枚举值非法时返回 400
- 数字类型转换失败时返回 400
- `extra_args` 非法时返回 400
- 前端保存失败时保留当前编辑值并显示错误

## 测试

后端新增或扩展 pytest 覆盖：

- CLI 参数 schema/读取/更新/重置 API
- `codex` 参数类型转换
- tunnel service 的状态流转
- tunnel API 在手工 `WEB_PUBLIC_URL` 与 quick tunnel 模式下的表现

前端新增 vitest 覆盖：

- 设置页显示 CLI 参数区块
- 修改布尔/枚举/列表参数
- 重置参数
- 设置页显示 tunnel 状态
- tunnel 启停按钮触发 API

## 非目标

- 不实现 Named Tunnel
- 不接入 Cloudflare Access
- 不增加多用户权限分级
- 不做通用 tunnel provider 抽象
- 不改旧 `kimi_web.py` / `webcli.py` 旧路线，只借用其 `cloudflared` 输出解析经验
