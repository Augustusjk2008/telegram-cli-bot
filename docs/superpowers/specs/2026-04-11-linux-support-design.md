# Linux Support And Webcli Removal Design

日期：2026-04-11

## 目标

为项目新增 Ubuntu/Debian 首发的 Linux 运行支持，同时删除已经退役的 `webcli` 遗留实现，并保持 Windows 继续作为正式支持平台。

本次设计的目标边界如下：

1. Linux 支持范围限定为核心运行支持：
   - Telegram bot
   - CLI 转发
   - assistant 模式
   - Web UI
   - 文件浏览
   - Git 页面
2. 删除旧 `webcli` 运行时代码，不再把它视为可选产品模式。
3. Windows 与 Linux 双平台并行维护，不转向 Linux-only。
4. Linux 首发运维目标明确为 Ubuntu/Debian，默认 shell 为 `bash`，文档按 `apt + systemd` 编写。

## 用户确认的约束

- 只做核心 Linux 运行支持，不把遗留 `webcli` 迁移到 Linux。
- `webcli` 不仅在 Linux 上不要，在 Windows 上也要删干净。
- Linux 首发支持层级选 Ubuntu/Debian 单线支持。
- Windows 仍需保留为正式支持平台。
- 设计过程中的架构决策需要写入仓库内文档，不能只停留在会话里。

## 现状

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py) 同时承担 CLI 可执行文件查找、Windows 扩展名兼容、PowerShell/`cmd.exe` 包装等职责，平台细节和业务逻辑耦合较深。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py) 中的进程终止逻辑对 Windows 做了专门兼容，但 Linux 进程组语义还没有被正式抽象成一等能力。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py)、[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py)、[C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/terminalSession.ts](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/terminalSession.ts) 仍把默认 shell 写死为 `powershell`。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py) 当前用统一的脚本扫描和执行逻辑处理 `.bat/.cmd/.ps1/.py/.exe`，它天然偏向 Windows，没有按平台过滤脚本可见性。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py) 的路径截断与用户提示里仍有明显的 Windows 路径假设，例如反斜杠格式和“Windows 常见为 `claude.cmd`”。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/utils/windowsPath.ts](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/utils/windowsPath.ts) 和多个前端 mock/test 样本把 Windows 路径当成默认输入与展示模型。
- 仓库中仍保留 `webcli` 遗留：
  - [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/webcli.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/webcli.py)
  - [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/combined_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/combined_server.py)
  - [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/data/webcli/index.html](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/data/webcli/index.html)
  - [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 与 [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py) 中的兼容分支

## 方案比较

### 方案 A：最小侵入兼容改造

- 在现有模块中继续增加 `sys.platform` / `os.name` 分支。
- 删除 `webcli`，其余位置维持当前文件边界。

优点：

- 实现速度快，短期改动小。

缺点：

- 平台差异会继续散落在多个业务模块中。
- Windows 与 Linux 长期并行维护的回归成本高。

### 方案 B：平台能力抽象层加定向清理

- 新增统一的平台能力层，收口 shell、脚本、CLI 可执行文件、进程树终止、路径展示等差异。
- 删除 `webcli` 遗留，把 bot mode 正式收敛为 `cli` 和 `assistant`。

优点：

- 更适合 Windows 与 Linux 双平台长期并行。
- 删除遗留与新增 Linux 支持可以一次性理顺边界。
- 后续扩展 CI、文档和运维脚本更稳定。

缺点：

- 比方案 A 多一轮结构调整。

### 方案 C：Linux 优先重构

- 以 Linux 为主重新定义 shell、脚本、路径和终端模型。
- Windows 只保留最低限度兼容。

优点：

- 结构最干净。

缺点：

- 与“Windows 继续正式支持”的目标冲突。

## 已选方案

采用方案 B：平台能力抽象层加定向清理。

理由：

- 用户要求 Linux 首发与 Windows 并行正式支持，这决定了平台差异不能继续散落在业务代码里。
- `webcli` 已经是逻辑上禁用、代码上残留的状态，继续保留兼容壳只会放大后续维护成本。
- 平台层能把本次变更拆成清晰的责任边界：运行时、CLI、终端、脚本、路径、文案各自收口。

## 总体架构

本次改造后的运行态只保留两个 bot mode：

- `cli`
- `assistant`

`webcli` 不再作为运行态概念存在。对于历史配置文件中的 `webcli`，仅在读取持久化配置时做一次性迁移为 `cli`，并在保存时写回新值。

整体架构采用“业务逻辑 + 平台能力层”模式：

- 业务层只表达“需要启动 CLI”“需要开启终端 shell”“需要执行系统脚本”“需要显示路径”。
- 平台层负责回答这些动作在 Windows 和 Linux 上分别怎样执行。
- 前端不再把 `powershell` 和 Windows 路径当成全局默认值，而是改成跨平台中性实现，必要时由后端提供平台默认。

这样 Linux 支持将成为显式架构能力，而不是分散的特判集合。

## 模块拆分

建议新增 `bot/platform/` 目录，最小拆分如下：

### `bot/platform/runtime.py`

职责：

- 识别当前运行平台。
- 统一提供平台名称、默认 shell、是否支持某类脚本等基础判断。

接口方向：

- `get_runtime_platform() -> Literal["windows", "linux"]`
- `get_default_shell() -> str`

### `bot/platform/executables.py`

职责：

- 解析 CLI 可执行文件。
- 构建最终进程启动命令，处理平台差异。

接口方向：

- `resolve_cli_executable(cli_path, working_dir)`
- `build_executable_invocation(resolved_path)`

Windows 行为：

- 支持 `.cmd/.bat/.exe/.com/.ps1`
- 继续兼容 npm 全局目录兜底

Linux 行为：

- 只支持 PATH 内命令、显式相对路径、绝对路径
- 不自动补 `.cmd/.bat/.ps1`
- 对 Windows 专属后缀给出清晰错误

### `bot/platform/processes.py`

职责：

- 统一进程树创建与终止策略。

接口方向：

- `build_subprocess_kwargs_for_platform() -> dict`
- `terminate_process_tree(process) -> None`

Windows 行为：

- 保留当前 `taskkill /T /F` 类策略

Linux 行为：

- 启动时使用 `start_new_session=True` 或等价进程组策略
- 终止时优先 `os.killpg`
- 超时后升级到强制 kill

### `bot/platform/scripts.py`

职责：

- 扫描系统脚本
- 过滤当前平台可见的脚本
- 生成脚本执行命令
- 解析脚本显示名和简介

Linux 首发支持扩展名：

- `.sh`
- `.py`

Windows 保留支持：

- `.ps1`
- `.bat`
- `.cmd`
- `.py`
- `.exe`

### `bot/platform/paths.py`

职责：

- 统一路径格式化、显示截断、样例路径生成、repo 名提取。

这里要吸收 [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py) 中当前只按 Windows 反斜杠工作的路径截断逻辑，改成双平台可读实现。

### 消息与文案层

不强制新增独立文件，但需要把平台相关用户提示收口，避免在业务逻辑里继续硬编码：

- “Windows 常见为 `claude.cmd`”
- “默认 shell 为 `powershell`”
- 路径 placeholder 和帮助文本

## 核心运行链路设计

### CLI 启动

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py) 需要收敛职责：

- 保留 CLI 类型校验、参数组装、Codex/Kimi/Claude 输出解析
- 将平台相关的可执行文件解析与包装迁移到平台层

数据流调整为：

1. 用户配置 `cli_path`
2. 平台层解析出真实可执行目标
3. CLI 参数层按 `cli_type` 生成业务参数
4. 平台层根据目标文件和当前平台生成最终命令
5. 业务层启动子进程

这样可以避免 `bot/cli.py` 继续同时理解 CLI 业务和平台脚本差异。

### 进程生命周期

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py) 中的 `/kill`、超时终止、会话重置，都要改为调用平台统一的进程树终止接口。

目标语义：

- 同一条 CLI 请求无论在 Windows 还是 Linux，终止粒度都应是“整个子进程树/进程组”
- Telegram `/kill`、Web 端 kill、超时清理三条路径共用同一终止能力

### Web 终端

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py) 当前 `/terminal/ws` 默认使用 `powershell`。改造后应调整为：

- 前端不再硬编码默认 shell
- 后端按平台提供默认 shell：
  - Windows: `powershell`
  - Linux: `bash`

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py) 需要把 Linux 的 PTY 支持提升为正式实现，而不是“Unix 分支启动了 PTY，但外层能力模型仍偏向非 PTY”的半兼容状态。

Linux 首发要求：

- shell 能稳定回显
- `Ctrl+C` 可用
- 长时间输出可读
- 常见交互命令不因 PTY 实现残缺而失真

### 管理脚本

[C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/admin.py) 当前对脚本列表和执行方式采用“同目录统一扫描”的策略。改造后应改为：

- 当前平台只显示当前平台支持的脚本
- Linux 上看不到纯 Windows 脚本
- Windows 上继续保留原有脚本能力
- 脚本说明提取逻辑补充 `.sh` 注释支持

这意味着 Linux 用户不会在 `/system` 或 Web 设置页看到一堆不可执行的 `.ps1/.bat` 项目。

### 路径与 UI

前端需要停止把 Windows 路径视为默认输入模型：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/utils/windowsPath.ts](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/utils/windowsPath.ts) 应改为跨平台输入规范化工具，或被更通用的实现替代
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/BotListScreen.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/BotListScreen.tsx) 中的 placeholder 应按平台展示不同示例
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/TerminalScreen.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/TerminalScreen.tsx) 与 [C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/terminalSession.ts](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/terminalSession.ts) 不再默认传 `powershell`

跨平台路径目标：

- 输入框只做必要的 trim 和基本校验
- 路径展示逻辑能同时处理 `C:\...` 和 `/srv/...`
- repo 名提取不能只依赖反斜杠分割

## Webcli 删除边界

本次明确删除以下遗留物：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/webcli.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/webcli.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/combined_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/combined_server.py)
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/data/webcli/index.html](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/data/webcli/index.html)
- `handle_webcli_*` 相关死代码
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 中 `profile.bot_mode == "webcli"` 分支
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py) 中对 `webcli` 的注册兼容分支
- 纯粹为了 `webcli` 存在的测试

保留但收窄的兼容行为：

- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py) 在加载旧配置时仍把 `webcli` 自动迁移为 `cli`
- 除配置迁移外，其余所有运行态代码都不再承认 `webcli`

## 错误处理

### CLI 路径错误

- Linux 上若用户配置 `.cmd/.bat/.ps1`，报错应明确指出这是 Windows 专属可执行形式
- Windows 上继续允许 `claude.cmd` 这类 npm shim

### 脚本执行错误

- Linux 上不展示不支持的脚本，避免“点了才发现不可用”
- 平台支持但执行失败时，维持当前输出捕获和超时反馈模型

### 终端失败

- 若 Linux PTY 创建失败，应返回明确错误，而不是静默回退成不可交互状态
- 前端终端页继续保留可读错误提示和重建入口

## 测试设计

后端测试分三层：

### 纯单元测试

- 平台探测
- CLI 可执行文件解析
- 脚本筛选
- 平台命令包装
- 路径截断与 repo 名提取
- 进程树终止策略分发

### 平台条件测试

- Windows 专属测试使用 `skipif(sys.platform != "win32")`
- Linux 专属测试使用 `skipif(sys.platform != "linux")`

### 跨平台契约测试

- bot mode 收敛为 `cli/assistant`
- Web API 结构保持稳定
- 工作目录修改、CLI 参数更新、文件/Git 能力不因平台不同而改变 API 语义

前端测试调整方向：

- 去掉固定 `powershell` 断言
- 重写或替换 `windowsPath` 相关测试，使其验证跨平台输入逻辑
- 将 `C:\workspace\...` 样本改为中性样本或分别覆盖 Windows/Linux 样本

CI 验证建议：

- Linux runner 作为主验证环境
- Windows runner 继续保留
- 首批至少覆盖：
  - Linux: `python -m pytest tests -q`、`cd front && npm test`、`cd front && npm run build`
  - Windows: 核心后端测试、前端测试、前端 build

## 运维与发布

Ubuntu/Debian 首发需要补齐：

- Linux 安装文档
- `.env.example` 中的 Linux 路径示例
- `systemd` 服务文件模板
- Linux 启动脚本，例如 `start.sh`

如果仓库继续保留 Windows 启动入口，例如 `start.bat`、`start.ps1`，则文档中必须明确：

- Windows 使用哪套入口
- Linux 使用哪套入口
- systemd 推荐方式与手工启动方式分别是什么

## 实施顺序

建议分 4 个阶段实施：

1. 删除 `webcli` 遗留与相关测试，先收敛产品边界
2. 引入平台能力层，改造后端 CLI、进程、脚本、路径逻辑
3. 改造 Web 终端与前端路径模型，去除 `powershell` 和 Windows 路径默认假设
4. 补 Linux 文档、`systemd` 模板、启动脚本和 CI

这样可以先降低历史噪音，再推进跨平台抽象，减少每一步的上下文复杂度。

## 风险

- Linux PTY 若实现不完整，Web 终端会出现回显、控制键和交互行为异常。
- 若脚本系统只改执行不改展示，Linux 用户仍会看到大量不可用脚本。
- 若前端继续把 Windows 路径作为默认样例，Linux 用户配置体验会持续偏差。
- 若测试仍主要使用 Windows 样本，Linux 支持很容易在后续迭代中回归失效。

## 非目标

- 不在本次支持 macOS。
- 不把 Linux 首发目标扩展到所有发行版。
- 不恢复或重建 `webcli` 的产品能力。
- 不在本次把所有运维脚本都强行改造成双平台对等版本；纯 Windows 脚本可保留，但 Linux 不展示、不执行。

