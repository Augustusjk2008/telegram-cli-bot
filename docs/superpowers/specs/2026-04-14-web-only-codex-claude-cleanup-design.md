# Web-Only Codex Claude Cleanup Design

日期：2026-04-14

## 目标

为项目设计一次明确收缩产品边界的清理改造，最终只保留以下运行能力：

- Web 管理界面与 Web 聊天入口
- `codex`
- `claude`
- 新的 `cli` bot
- 新的 `assistant` bot

本次清理完成后，不再保留以下对象作为运行时能力：

- Telegram runtime
- Telegram 发送与通知能力
- `kimi`
- 旧的非 CLI assistant 兼容形态

这里的“新 assistant bot”定义为：

- `bot_mode="assistant"`
- 实际仍走 CLI 聊天链路
- 在发送前编排 assistant prompt
- 在收尾时写 `.assistant/` 私有状态

它不是旧的“自带工具运行时、独立于 CLI 会话”的 assistant。

## 用户确认的约束

- Telegram 不是“先禁用”，而是要彻底移除 runtime 与所有发送能力。
- 只保留 Web 作为入口面。
- 只保留 `codex` 与 `claude` 两种 CLI provider。
- 删除过程不能影响要保留的功能。
- 与保留目标无关的遗留代码应主动删除，而不是长期冻结。
- 本次先完成设计，不直接做大规模代码删除。

## 保留边界

### 保留的产品面

- Web API 与前端界面
- Web chat
- Web 文件浏览
- Web Git 页面
- Web 终端
- bot 管理与设置页面
- `cli` / `assistant` 两种 bot mode
- `codex` / `claude` 两种 provider
- assistant 的 `.assistant/` home、proposal、upgrade、managed prompt、runtime state

### 明确保留的核心模块

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_builder.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_builder.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli_params.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli_params.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_home.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_home.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_context.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_context.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_state.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_state.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_docs.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_docs.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_proposals.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_proposals.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_upgrade.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_upgrade.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/front](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front)

## 非目标

- 不在本次设计中重做前端交互风格。
- 不在本次设计中替换 Web API 框架。
- 不在本次设计中重新设计 assistant proposal / upgrade 机制。
- 不把“仓库改名”作为首批清理阻塞项。
- 不为 `kimi`、Telegram、旧 assistant 做新的兼容性设计。

## 当前现状

### 1. Telegram 仍是主运行时，而不是可直接删除的边角功能

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/main.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/main.py) 当前仍以 Telegram lifecycle 为主线：

- `main_profile` 直接持有 Telegram token
- `run_all_bots()` 同时负责 Telegram polling 和 Web server
- `TELEGRAM_ENABLED` 决定是否启动核心运行链

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py) 也仍以 Telegram `Application` 为中心：

- profile 启动等价于启动 Telegram application
- watchdog 关注 Telegram updater
- manager alert 通过 Telegram 主 bot 推送

这意味着 Telegram 不是一个独立目录，可以直接整包删掉；它仍然定义了主进程与 manager 的生命周期模型。

### 2. Web 层仍然借用了 Telegram 时代的实现

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 当前仍引用：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py) 里的脚本执行逻辑
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/shell.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/shell.py) 里的 `strip_ansi_escape`

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py) 当前仍引用：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py) 的终端创建逻辑
- Telegram `Bot` 与 `HTTPXRequest` 用于 tunnel 地址推送

这说明 Telegram handler 目录里混有 Web 仍在复用的公共能力，不能先删目录再补洞。

### 3. `kimi` 已经渗透到 provider、session、配置与前端

`kimi` 目前不是孤立 provider，而是已经进入：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/config.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/config.py) 的 `SUPPORTED_CLI_TYPES`
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py) 的 CLI 类型校验与 reset 语义
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli_params.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli_params.py) 的默认参数与 schema
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/models.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/models.py) 的 `kimi_session_id`
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py) 与 [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/session_store.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/session_store.py) 的恢复/持久化格式
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 的 session 分支与 chat 分支
- 前端 CLI 类型枚举与 bot 设置页面

这意味着 `kimi` 的正确移除方式不是删一个 provider 文件，而是做一次跨后后端与前端的数据模型收缩。

### 4. “旧 assistant”不是一个可整包删除的目录

仓库内真正需要保留的是 CLI-backed assistant：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_home.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_home.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_context.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_context.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_state.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_state.py)

而要删除的是旧兼容形态：

- 只为 Telegram assistant 服务的上下文装配壳
- 只为旧 history 形态存在的兼容分支
- 只为了兼容旧非 CLI assistant 而保留的状态字段和测试假设

因此 assistant 不能按“看见 `assistant_*` 就删”的方式处理。

### 5. Telegram 语音能力天然属于待删除范围

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/voice.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/voice.py) 与 [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/whisper_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/whisper_service.py) 当前完全挂在 Telegram handler surface 上。

如果 Telegram runtime 被彻底删除，而用户又没有提出“保留 Web 语音”，那么：

- 语音 handler
- Whisper 的 Telegram 接入口
- `requirements-voice.txt` 在 README 中的主路径说明

都应视为可删对象。

## 方案比较

### 方案 A：整仓硬删

- 直接删除 Telegram 目录与 `kimi` 分支
- 发现报错后再逐步补救

优点：

- 速度最快
- 视觉上最“干净”

缺点：

- 极易误删 Web 仍在借用的逻辑
- 很难分清“真正遗留”与“共享基座”
- 回归面会在一个提交里同时炸开

### 方案 B：只禁用，不删除

- 配置层不再暴露 Telegram 与 `kimi`
- 运行时尽量不触发旧路径
- 代码暂时保留

优点：

- 风险低

缺点：

- 与“该删就删”的目标冲突
- 后续维护成本几乎不降

### 方案 C：先解耦，再分批删除

- 先从共享模块中抽出 Web 仍需的公共能力
- 再按 `kimi -> Telegram runtime -> 旧 assistant 兼容层` 的顺序分批删除
- 每一批都配套清理测试、配置格式与文档

优点：

- 最符合“不能影响保留功能”的要求
- 每一批都有清晰回归边界
- 能在删除后真正收缩代码体积和产品边界

缺点：

- 需要一轮中间态重组
- 比硬删多一个“抽离共享能力”的步骤

## 已选方案

采用方案 C：先解耦，再分批删除。

理由：

- 当前 Web 仍深度复用 Telegram 时代的 manager、handler 和终端/脚本逻辑。
- `kimi` 的删除是跨数据模型的，不是单文件删除。
- assistant 需要保留的部分与要删除的旧兼容部分交织，必须先明确边界。
- 只有按阶段拆开，才能让每一轮回归都与保留功能对应。

## 总体架构方向

清理后的系统应收敛为“纯 Web 宿主 + 两种 CLI provider + 两种 bot mode”：

- 入口：Web
- provider：`codex` / `claude`
- bot mode：`cli` / `assistant`

主进程的生命周期也应从“Telegram first，Web optional”改为“Web first，bot runtime embedded”：

- 主进程启动时只初始化本地 profile 管理、Web API server、可选 tunnel
- 不再初始化 Telegram `Application`
- 不再维护 Telegram polling watchdog
- 不再发送 Telegram 告警与公网地址通知

manager 也应从“Telegram application orchestration”收敛为“bot profile orchestration”：

- 管理 profile
- 管理启停状态
- 管理 session 与工作目录
- 提供 Web 侧所需的 bot 列表与状态

但不再承担：

- Telegram app 构建
- polling restart
- Telegram network retry
- 发送 Telegram 消息

## 删除顺序设计

### 阶段 0：先锁验收口径

在任何删除动作之前，先明确本次唯一验收目标：

- Web
- `codex`
- `claude`
- 新 `cli`
- 新 `assistant`

不再将以下对象视为回归阻塞项：

- Telegram
- `kimi`
- 旧非 CLI assistant

这一步的意义不是删代码，而是先改测试与验收心智，防止后续每删一层都被旧目标拉回去。

### 阶段 1：先删除 `kimi`

先删 `kimi` 的原因：

- 它比 Telegram runtime 更独立
- 它的删除有利于先收缩 profile、session、CLI 参数和前端表单模型
- 删除后能明显减少后续 manager / Web API 分支数量

本阶段的动作包括：

- 删除 `SUPPORTED_CLI_TYPES` 中的 `kimi`
- 删除 `kimi` 参数 schema 与默认值
- 删除 `kimi_session_id`
- 删除 `should_reset_kimi_session()`
- 删除 `run_chat` / `stream_chat` 中的 `kimi` 分支
- 删除前端 CLI 类型枚举中的 `kimi`
- 删除 `kimi` 头像、mock、README、测试
- 删除 [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/kimi_web.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/kimi_web.py)

迁移策略：

- 历史持久化的 `kimi_session_id` 直接忽略并在下次写回时消失
- `managed_bots.json` 中若存在 `cli_type="kimi"`，启动时应明确报错，要求人工迁移，不自动替换 provider

### 阶段 2：抽离 Web 仍需的公共能力

这一步是整次清理的关键中间层。

需要抽离的能力包括：

- 系统脚本扫描与执行
- ANSI 清洗
- Web 终端进程创建
- 可能仍有价值的通用文件/进程辅助函数

建议形成新的归属：

- `bot/web/scripts.py` 或 `bot/platform/scripts.py`
- `bot/platform/terminal.py`
- `bot/platform/output.py`

目标是让以下文件不再依赖 Telegram handler 目录：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py)

只有完成这一步，后面才能真正删除 `bot/handlers/`。

### 阶段 3：删除 Telegram runtime

当 Web 与共享公共能力已经解耦后，再清主运行链：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/main.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/main.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/config.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/config.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py)

本阶段要完成的边界收缩：

- 删除 `TELEGRAM_ENABLED`
- 删除 `TELEGRAM_BOT_TOKEN`
- 删除 `python-telegram-bot` 依赖
- 删除 polling / watchdog / retry / Telegram app 生命周期
- 删除 manager 告警的 Telegram 投递
- 删除 tunnel 地址的 Telegram 推送

调整后的 `main_profile` 不再代表 Telegram 主 bot，而是本地默认 bot profile。

### 阶段 4：删除 Telegram handler 与语音入口

在阶段 2 完成之后，可以直接删除：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/basic.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/basic.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/file.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/file.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/file_browser.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/file_browser.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/shell.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/shell.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/voice.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/voice.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/context_helpers.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/context_helpers.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/whisper_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/whisper_service.py)

删除标准：

- Web 代码不得再 import `bot.handlers.*`
- 运行时代码不得再 import `telegram`

### 阶段 5：清理旧 assistant 兼容层

需要保留的新 assistant 能力：

- assistant home bootstrap
- managed prompt sync
- assistant runtime state
- capture / compaction
- proposal / upgrade

需要删除的旧兼容对象：

- 只为 Telegram assistant 恢复私有 history 的路径
- 对 `session.history` 的旧式依赖
- 只为旧 assistant shell 提供的测试和文档说明

目标是让 assistant 最终只剩：

- CLI-backed prompt orchestration
- `.assistant/` 私有目录
- Web 侧管理与审批接口

## 关键模块的目标形态

### `bot/config.py`

收敛为：

- Web 配置
- CLI 配置
- 本地运行配置
- tunnel 配置

删除：

- Telegram token
- Telegram enable flag
- Telegram 代理说明
- 只为 Telegram 存在的常量

`SUPPORTED_CLI_TYPES` 最终只剩：

- `codex`
- `claude`

### `bot/models.py`

`BotProfile` 需要收缩：

- `token` 应退场，或至少降为迁移期可选字段，最终不再参与运行

`UserSession` 需要收缩：

- 删除 `kimi_session_id`
- 重新审视 `history` 的职责，避免旧 Telegram/assistant 语义继续存活

### `bot/sessions.py` 与 `bot/session_store.py`

目标：

- 持久化只服务 Web + `codex/claude` + 新 assistant
- 删除 `kimi_session_id`
- 忽略旧 Telegram/assistant 的历史恢复形态

迁移策略：

- 读取旧字段时容忍，但不再写回
- 新格式中彻底去掉 `kimi_session_id`

### `bot/manager.py`

目标是从 “Telegram bot orchestrator” 改成 “local bot profile manager”。

应保留：

- `managed_bots.json` 读写
- profile 增删改查
- `cli` / `assistant` 限制校验
- 会话与工作目录协同

应删除：

- `Application`
- polling
- updater watchdog
- Telegram 报警发送
- token 冲突校验

### `bot/web/server.py`

应保留：

- API 路由
- SSE
- terminal websocket
- tunnel 管理
- 管理端 bot / assistant 接口

应删除：

- Telegram Bot 初始化
- quick tunnel 地址 Telegram 推送
- `telegram_running` 这类健康字段

### `front/*`

应完成的收缩：

- `CliType` 只剩 `codex | claude`
- bot 创建/编辑页面只展示两种 provider
- 删除 `kimi` mock 与头像
- 文案不再把 Telegram 作为入口之一

## 需要删除的主要代码面

### 运行时代码

- Telegram imports
- Telegram runtime config
- Telegram lifecycle
- Telegram handler registry
- Telegram voice entry
- `kimi` provider branches

### 测试

- Telegram handler 测试
- Telegram context helper 测试
- Telegram 语音测试
- `kimi` provider 测试
- 任何把 Telegram 或 `kimi` 视为应通过主回归面的测试

### 文档

- README 中的 Telegram 主入口描述
- README 中的 `kimi` 支持说明
- Web-only 模式下“可通过 Telegram 推送 tunnel 地址”的描述
- 语音安装作为主路径说明

## 风险与控制

### 风险 1：误删 Web 仍在用的共享能力

控制方式：

- 明确以“阶段 2 抽离共享能力”为删除前置条件
- 删除 `bot/handlers` 前先让 Web import 清零

### 风险 2：manager 改造过快导致 bot 管理面失效

控制方式：

- 先保留 `managed_bots.json` 与 profile 管理接口
- 先删 Telegram 生命周期，再删 Telegram 特定字段

### 风险 3：assistant 被误判为“旧功能”而被过删

控制方式：

- 以“CLI-backed assistant”作为唯一保留定义
- 保留 `.assistant/` 相关模块与 Web assistant 审批接口

### 风险 4：旧本地配置文件迁移失败

控制方式：

- 对旧字段读取保持宽容
- 写回时只写新格式
- 对 `cli_type="kimi"` 做显式错误，而不是静默替换

## 验证策略

每个阶段都应以“保留功能可验证”为准，而不是只看编译通过。

### 后端主验证

- Web 启动测试
- Web API 测试
- native history / rich events 测试
- assistant home / context / state / docs / proposals / upgrades 测试

### 前端主验证

- app 基础交互测试
- chat screen
- files screen
- git screen
- settings / bot list

### 最终运行态验证

- `python -m bot` 在没有 Telegram 环境变量时可直接启动
- Web 能创建、删除、编辑、启停 `cli` / `assistant` bot
- `codex` / `claude` Web chat 正常
- assistant 的 prompt、state、proposal、upgrade 正常
- 文件、Git、终端、设置页面正常

## 最终验收标准

当以下条件全部满足时，本次清理视为完成：

1. 运行时代码不再 import `telegram`。
2. 项目运行不再依赖 Telegram token、Telegram enable flag、Telegram bot lifecycle。
3. 运行时代码的 CLI 类型只剩 `codex` 与 `claude`。
4. Web 功能保持完整可用。
5. 新 `assistant` bot 保持完整可用。
6. `kimi`、Telegram、旧 assistant 兼容逻辑从主代码与主文档中清除。
7. 删除结果不是“隐藏旧功能”，而是确实让代码面与配置面都收缩。

## 建议的实施顺序

推荐把后续实施拆成六个连续的变更批次：

1. 锁验收口径并删除 `kimi`
2. 抽离 Web 仍需的公共能力
3. 删除 Telegram runtime
4. 删除 Telegram handler、context helper 与 voice
5. 清理旧 assistant 兼容层
6. 清理文档、依赖、启动脚本与配置迁移

这个顺序的核心原则是：

- 先减 provider 复杂度
- 再解耦共享基座
- 最后做大块删除

这样能最大限度避免“删得很干净，但 Web 被一起删坏”的结果。
