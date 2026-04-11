# Allow Empty Telegram Token In Web-Only Mode Design

日期：2026-04-11

## 目标

允许用户在纯 Web 模式下将 `.env` 中的 `TELEGRAM_BOT_TOKEN` 留空，并保证系统在这种模式下完全不触碰 Telegram。

具体目标：

1. 当 `TELEGRAM_ENABLED=false` 且 `WEB_ENABLED=true` 时，允许 `TELEGRAM_BOT_TOKEN` 为空。
2. 当 `TELEGRAM_ENABLED=true` 时，仍然要求 `TELEGRAM_BOT_TOKEN` 有效，保持当前报错行为。
3. 纯 Web 模式下不启动 Telegram 轮询，也不发送任何 Telegram 消息。
4. Cloudflare Quick Tunnel 在纯 Web 模式下仍可正常工作，但公网地址只在 Web 页面和本机剪贴板中可见，不通过 Telegram 推送。

## 用户确认的约束

- 只有 `TELEGRAM_ENABLED=false` 时才允许空 token。
- 只要 Telegram 关闭，就不应有任何 Telegram 相关动作。
- Telegram 开启但 token 为空时，仍然应该阻止启动并提示配置错误。

## 现状

- [bot/main.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/main.py) 当前在 `TELEGRAM_ENABLED=true` 时会校验 `TELEGRAM_BOT_TOKEN != "your_bot_token_here"`，但没有把“空字符串”与“仅 Web 模式”作为明确规则写出来。
- [bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py) 已经通过 `_profile_uses_telegram()` 用 token 是否非空判断某个 profile 是否真正使用 Telegram；token 为空时会跳过 Telegram `Application` 创建。
- [bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py) 的 tunnel 通知逻辑会尝试把公网地址复制到剪贴板，并在主 Telegram application 存在时向 `ALLOWED_USER_IDS` 发送消息。
- 当前文档与 `.env.example` 还没有明确表达“纯 Web 模式可以不配置 Telegram token”。

## 方案

本次采用最小改动方案：

- 启动校验层按 `TELEGRAM_ENABLED` 决定是否强制要求 `TELEGRAM_BOT_TOKEN`。
- Telegram 生命周期仍复用 `MultiBotManager._profile_uses_telegram()` 作为“是否真的要启动 Telegram”的唯一判断。
- Tunnel 公网地址通知保持“复制到剪贴板”的本地行为，但只有在主 Telegram application 已启动时才尝试 Telegram 推送。
- 文档与示例配置同步改为显式说明：纯 Web 模式允许 token 留空。

不引入新的配置项，也不把 token 是否为空改成自动推断 `TELEGRAM_ENABLED` 的来源。

## 后端设计

### 启动校验

在 [bot/main.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/main.py) 中把 Telegram token 校验明确成：

- 若 `TELEGRAM_ENABLED=true`：
  - token 不能为空
  - token 不能等于占位值 `your_bot_token_here`
  - 不满足时直接报错退出
- 若 `TELEGRAM_ENABLED=false`：
  - 不校验 token
  - 允许 token 为空字符串

这样可以让纯 Web 用户完全不接触 Telegram 配置，同时保持 Telegram 模式的显式失败行为。

### Telegram 启动边界

[bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py) 继续保持当前语义：

- profile 的 token 非空时，才创建 Telegram `Application`
- profile 的 token 为空时，记录“仅保留 Web 访问”的日志并跳过 Telegram 启动

这里不改成读取 `TELEGRAM_ENABLED`，因为主进程本身已经决定是否进入 Telegram 轮询路径；manager 的职责只保留在“某个 bot profile 是否具备 Telegram 启动条件”。

### Tunnel 通知

[bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py) 的 `_notify_tunnel_public_url()` 维持以下边界：

- 仍然在获得 Quick Tunnel URL 后尝试复制到本机剪贴板
- 只有主 Telegram application 存在时，才尝试 Telegram 推送
- 若主 Telegram application 不存在，直接返回“不发送 Telegram 通知”的结果，不视为错误

这保证纯 Web 模式下：

- tunnel 自动启动仍然可用
- Web 设置页仍能看到公网地址
- 不会出现“因为 token 为空还去尝试推送 Telegram 消息”的路径

## 数据流

### 纯 Web 模式启动

1. 用户在 `.env` 中设置 `TELEGRAM_ENABLED=false`
2. `TELEGRAM_BOT_TOKEN` 留空
3. 主进程启动时跳过 Telegram token 校验
4. `run_all_bots()` 不启动 Telegram manager 轮询
5. 若 `WEB_ENABLED=true`，则正常启动 Web API
6. 若配置了 Quick Tunnel，则启动 tunnel
7. 获得公网地址后只做本地剪贴板复制，不发 Telegram 消息

### Telegram 模式启动

1. 用户在 `.env` 中设置 `TELEGRAM_ENABLED=true`
2. 若 token 为空或仍为占位值，主进程直接报错退出
3. 若 token 有效，则继续当前 Telegram 启动流程

## 错误处理

- `TELEGRAM_ENABLED=true` 且 token 为空：报错“请设置 TELEGRAM_BOT_TOKEN 环境变量”
- `TELEGRAM_ENABLED=true` 且 token 为占位值：同样报错
- `TELEGRAM_ENABLED=false` 且 token 为空：不报错
- 纯 Web 模式下 tunnel 启动成功但没有 Telegram application：不记为失败，不重试 Telegram 推送

## 测试

后端新增或调整 pytest 覆盖：

- `main()` 在 `TELEGRAM_ENABLED=false` 且 token 为空时不会因 token 校验退出
- `main()` 在 `TELEGRAM_ENABLED=true` 且 token 为空时会退出
- `main()` 在 `TELEGRAM_ENABLED=true` 且 token 为占位值时会退出
- `_notify_tunnel_public_url()` 在没有主 Telegram application 时只复制剪贴板、不发送消息
- Web server 自动启动 tunnel 时，在纯 Web 模式下不会尝试 Telegram 推送

文档同步覆盖：

- [README.md](C:/Users/JiangKai/telegram_cli_bridge/refactoring/README.md) 明确说明纯 Web 模式可留空 `TELEGRAM_BOT_TOKEN`
- [.env.example](C:/Users/JiangKai/telegram_cli_bridge/refactoring/.env.example) 明确标注该字段在纯 Web 模式下可留空

## 非目标

- 不新增 `TELEGRAM_OPTIONAL` 之类的新配置项
- 不根据 token 是否为空自动改写 `TELEGRAM_ENABLED`
- 不改多 Bot 的持久化格式
- 不改变已有 Telegram 正常模式下的启动与告警行为
