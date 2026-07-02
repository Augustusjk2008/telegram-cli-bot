# Agent 指南

本文件说明本仓库内 coding agent 的工作约定。

## 会话约束

- 当前 agent 工作目录固定为 `C:\Users\JiangKai\telegram_cli_bridge\refactoring`
- 不得主动关闭、重启、kill 当前 agent 自身，或通过停服务/重启服务等方式让当前 agent 退出
- 如需重启 `python -m bot`、Web 服务或其它宿主进程，先让用户执行，或取得明确指令

## 项目概况

Orbit Safe Claw 是 Windows 优先的 Python Web 控制台，用于把用户消息转发给本地 AI coding CLI。

- CLI 目标：`claude`、`codex`
- 运行模式：`cli`、`assistant`
- Chat 执行模式：`cli`、`native_agent`
- 主 bot 来自 `.env`；托管子 bot 来自本地 `managed_bots.json`
- 同时最多允许一个 `assistant` bot profile
- Web UI 覆盖 chat、assistant ops、files、Git、terminal/debug、plugins、settings、admin center、announcements、updates、tunnel status

## 常用命令

```bash
# 安装 / 启动
bash install.sh
bash start.sh
python -m bot

# 后端测试
python -m pytest tests/test_cli.py tests/test_manager.py tests/test_sessions.py tests/test_session_store.py tests/test_web_auth_store.py tests/test_env_service.py tests/test_runtime_paths.py tests/test_runtime_web_startup.py tests/test_main_web.py -q

# 前端测试 / 构建
cd front && npm run test:gate
cd front && npm run build
cd front && npm run lint

# Release
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree -ReleaseNotesFile .\docs\release-notes\v<version>.md
```

不要假设仓库内 `venv/` 在所有机器可用。优先使用当前激活的 Python 环境，除非已验证本地 venv。

## 目录结构

```text
.
├─ bot/                    # 后端、Web API、bot manager、native agent、plugins
├─ front/                  # React/Vite 前端
├─ tests/                  # 后端 pytest
├─ examples/plugins/       # 示例插件
├─ docs/                   # 本地资料、计划和参考文档
├─ scripts/                # 辅助脚本
├─ deploy/                 # 发布/部署材料
├─ install.* / start.*     # 安装和启动脚本
└─ AGENTS.md               # 本文件
```

不要提交或 force-add：

- `.env`
- `managed_bots.json`
- `docs/` 运行态资料和 release notes
- 用户目录 `.tcb/` 下运行态数据

## 运行结构

### 入口

- `bot/__main__.py` 导入 `bot/main.py:main()`
- `main()` 在 restart loop 内执行 `asyncio.run(run_all_bots())`
- `/restart` 设置 `config.RESTART_REQUESTED` 和 `config.RESTART_EVENT`，再 re-exec 进程

### Multi-Bot Manager

`bot/manager.py:MultiBotManager` 管理 bot profile。

- `managed_bots.example.json` 是公开示例；不要提交真实 `managed_bots.json`
- 当前 runtime 仅 Web；不再有 per-bot Telegram application lifecycle
- 测试门禁和分类见 `docs/testing-policy.md`

## 核心区域

### Sessions 和 Chat History

`bot/sessions.py` 按 `(bot_id, shared_user_id, agent_id)` 存 session。Web user 通过 `bot/chat_identity.py:chat_session_user_id()` 归一化。

`UserSession` 跟踪当前工作目录、processing state、active subprocess、active conversation id、`codex` / `claude` / `native_agent` 原生 session id。

- 原生 session id 持久化到 `.session_store.json`
- chat history 通过 `bot/web/chat_store.py` 持久化
- 原生 agent conversation 额外持久化 `native_session_id`、`native_session_meta` 和 turn 级 `context_usage`
- 运行态和 overlays 保留在内存

### CLI Chat Flow

- Web/shared chat 路径：`bot/web/api_service.py`
- 命令构造和 CLI 参数：`bot/cli.py`、`bot/cli_params.py`
- 原生 agent 路径：`bot/native_agent/service.py`、`bot/native_agent/turn_state.py`、`bot/native_agent/ag_ui_mapper.py`
- Pi 主链模块：`bot/native_agent/pi_rpc_client.py`、`bot/native_agent/pi_events.py`、`bot/native_agent/pi_session_runtime.py`、`bot/native_agent/pi_session_store.py`、`bot/native_agent/pi_workspace_history.py`、`bot/native_agent/pi_rpc_preflight.py`
- Pi / `pi-workspace-history` 本地资料见 `docs/reference/pi/INDEX.md`；先查本地资料，除非需确认最新版。
- 支持的 CLI 类型：`claude`、`codex`

关键行为：

- 用户文本以 `//` 开头时改写为 `/...`
- Codex 使用 JSON output，由 `parse_codex_json_output()` 解析
- 长 Web 回复在 Web API 层 streaming 和 finalize
- `execution_mode=native_agent` 使用 AG-UI 协议；普通 CLI legacy SSE 保持 `delta/status/trace/done`
- Pi runtime 只允许 `pi_session_runtime.py` 单 reader 读取 `client.events()`；工作区历史由本地 shadow git 处理，不再依赖 Pi `workspace_history` RPC
- Pi 会话绑定指纹固定为 `cwd + model_id + pi_agent + reasoning_effort`；任一项变化都要失效旧 session 和 workspace history rollback 链
- 普通 CLI trace 只进入 `ChatTracePanel`；只有原生来源使用 `NativeAgentTranscript`
- CLI SSE 的 `meta/status/trace/done` 顶层带 `turn_id`、`assistant_message_id`，用于前端稳定绑定当前轮
- CLI bot 可定义 child agents；非 cluster chat 只绑定一个 active agent，cluster mode 通过 `@agent_id` 分发 child agents

### Pi 原生 agent 环境（非绿色版）

当前 Pi 扩展只有：

- `workspace-history.ts`：来自 `pi-workspace-history@0.2.2`，放入 Pi 自动发现扩展目录；提供 Pi 侧 `/checkpoint`、`/undo`、`/redo` 等工作区历史能力。Web rollback 仍以本地 `ShadowGitHistory` 为准。
- `tcb-cluster.ts`：本仓库 `bot/cluster/pi_extension/tcb-cluster.ts`，放入 Pi 自动发现扩展目录；注册 `cluster_status`、`list_agents`、`ask_agent`、`poll_agent_tasks`、`wait_agent_messages`。运行时依赖 `TCB_CLUSTER_MCP_CONFIG` 和 `TCB_CLUSTER_RUN_ID`，由 Web cluster/native agent 链路注入。

Pi 扩展目录规则：

- 默认：`~/.pi/agent/extensions`
- 设置 `PI_AGENT_SETTINGS=/path/to/settings.json` 时：`/path/to/extensions`
- 设置 `NATIVE_AGENT_PI_HOME=/path/to/pi-home` 时，Pi 子进程把该目录当 HOME，扩展目录为 `/path/to/pi-home/.pi/agent/extensions`

Linux / macOS 非绿色版安装：

```bash
# 先装 Node.js 22+、Git、bash
npm install -g @earendil-works/pi-coding-agent@0.74.2 pi-workspace-history@0.2.2
mkdir -p ~/.pi/agent/extensions
cp "$(npm root -g)/pi-workspace-history/.pi/extensions/workspace-history.ts" ~/.pi/agent/extensions/workspace-history.ts
cp ./bot/cluster/pi_extension/tcb-cluster.ts ~/.pi/agent/extensions/tcb-cluster.ts
pi --version
```

Windows 非绿色版安装：

```powershell
# 先装 Node.js 22+ 和 Git for Windows；Git Bash 要可用
npm install -g @earendil-works/pi-coding-agent@0.74.2 pi-workspace-history@0.2.2
New-Item -ItemType Directory -Force "$HOME\.pi\agent\extensions" | Out-Null
$npmRoot = npm root -g
Copy-Item "$npmRoot\pi-workspace-history\.pi\extensions\workspace-history.ts" "$HOME\.pi\agent\extensions\workspace-history.ts" -Force
Copy-Item ".\bot\cluster\pi_extension\tcb-cluster.ts" "$HOME\.pi\agent\extensions\tcb-cluster.ts" -Force
pi --version
```

`.env` 至少配置：

```env
NATIVE_AGENT_ENABLED=true
NATIVE_AGENT_PI_COMMAND=pi
# 如隔离 Pi HOME：
# NATIVE_AGENT_PI_HOME=/abs/path/to/pi-home
```

Pi 模型配置写 Web 设置页，或直接写 `~/.pi/agent/settings.json` 和 `~/.pi/agent/models.json`；如设置 `PI_AGENT_SETTINGS`，`models.json` 默认和它同目录。Windows 下 Pi shell 异常时，在 `settings.json` 写 `shellPath` 指向 Git Bash，如 `C:\\Program Files\\Git\\bin\\bash.exe`。

### Web API 和 Frontend

- 后端 API：`bot/web/server.py`、`bot/web/api_service.py`、`bot/web/git_service.py`
- 前端 app：`front/`
- 前端 screen 包括 chat、files、Git、terminal、debug、plugins、settings、assistant ops、admin center
- 已完成 assistant 回复用 Markdown 渲染，失败时 fallback 到 raw text
- plugin file view 支持 session-backed heavy views 和 VCD waveform rendering
- Git UI 支持 overview、diff、stage/unstage、commit、fetch/pull/push、stash/pop

## Plugin System

Plugin 默认位于 `Path.home() / ".tcb" / "plugins"`。示例 Vivado waveform plugin 位于 `examples/plugins/vivado-waveform`，会 copy/sync 到用户 plugin 目录供本地使用。

关键模块：

- manifest loading：`bot/plugins/manifest.py`
- registry 和 file matching：`bot/plugins/registry.py`
- runtime process 管理：`bot/plugins/runtime.py`
- orchestration、session cache、hot reload、config 写入：`bot/plugins/service.py`
- Web routes：`bot/web/api_service.py`、`bot/web/server.py`

`plugin.json` 支持 schema version 1 和 2。

- v1：`enabled`、可变 `config`、`views[].viewMode`（`snapshot` / `session`）、`views[].dataProfile`（`light` / `heavy`）
- v2 增加 runtime permissions、`configSchema`、`catalogActions`

通过 Web API 更新 plugin 会写 `plugin.json`、清理 plugin view sessions、关闭 plugin runtime，下次访问再从磁盘 reload。刷新 plugin 页面也会重新扫描 manifest 并重启 plugin runtime。

Vivado waveform plugin 使用 Python JSON-RPC stdio backend。它按 source fingerprint 建 VCD index，返回 summary 和 initial window，并按需提供可见 time/signal window。`config.lodEnabled` 控制 dense-segment LOD；dense 压缩不得隐藏 signal activity。

## 安装和更新

- Windows install：`install.bat`、`install.ps1`
- Linux install：`install.sh`
- Windows startup：`start.bat`、`start.ps1`
- Linux startup：`start.sh`
- 自动更新只检查 GitHub Releases
- `docs/` 必须保持在 git 外；release note 也不要 force-add 或提交
- GitHub Release body 来自 `.release-local/publish-release.ps1 -ReleaseNotesFile <markdown-file>`；省略则用 `gh release create --generate-notes`
- Web 公告运行时文件不在仓库根；从 `bot/runtime_paths.py:get_announcements_content_path()` 取，默认 `Path.home() / ".tcb" / "orbit-safe-claw" / "announcements" / "content.json"`，可被 `TCB_DATA_DIR` 覆盖。仓库根 `.web_announcements.json` 仅旧数据迁移用，不要作为当前公告维护位置
- 下载的更新在下次启动时通过 `python -m bot.updater apply-pending --repo-root <repo>` 应用

## 约定

- 用户可见文案使用中文
- Brand/logo assets 位于 `front/public/assets/app-logo*.svg`；login page、favicon、mobile shell、workbench header 应保持一致
- config 从 `bot/config.py` 的环境变量加载；`.env` 使用 `python-dotenv`
- 有后端和前端测试；未配置后端 linter/type checker

## CodeGraph

- 跨模块修改、架构分析、重构、调用链或影响面分析前，优先用可用的 CodeGraph MCP 工具，如 `codegraph_context`、`codegraph_search`、`codegraph_trace`、`codegraph_node`
- CodeGraph 只作导航；细节仍需用源码阅读、`rg`、测试、日志、`git diff` 核对
- 普通改动由 watcher 自动同步；大规模结构变更后，运行 `codegraph sync .` 或 `codegraph index .` 刷新 `.codegraph/codegraph.db`
- 已知文件小改、配置改动、文案改动、单文件 bug 不强制用 CodeGraph
- 如 CodeGraph 不可用，简述原因后改用 `rg` / 读源码，不要卡住任务

## 测试说明

- 避免在 component/page/shell 测试里重复断言同一事实；保留最合适的一层
- 后端测试使用 `pytest`、`pytest-asyncio`、`unittest.mock`
- 常用 fixtures：`tests/conftest.py` 中的 `mock_update`、`mock_context`、`clean_sessions`
- 原生 agent / context usage 相关测试：`tests/test_native_agent.py`、`tests/test_native_agent_context_usage.py`、`tests/test_sessions.py`
- 前端测试使用 Vitest、Testing Library、Playwright（浏览器级 layout check）
- 常用前端测试：`front/src/test/chat-screen.test.tsx`、`real-client.test.ts`、`ag-ui-stream-adapter.test.ts`、`desktop-bot-manager-screen.test.tsx`、`files-screen.test.tsx`、`git-screen.test.tsx`、`app.test.tsx`、`mobile-layout.spec.ts`
