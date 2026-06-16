# Agent 指南

本文件说明本仓库内 coding agent 的工作约定。

## 会话约束

- 当前 agent 工作目录固定为 `C:\Users\JiangKai\telegram_cli_bridge\refactoring`
- 不得主动关闭、重启、kill 当前 agent 自身，或通过停服务/重启服务等方式让当前 agent 退出
- 如需重启 `python -m bot`、Web 服务或其它宿主进程，先让用户执行，或取得明确指令

## 项目概况

Orbit Safe Claw 是 Windows 优先的 Python Web 控制台，用于把用户消息转发给本地 AI coding CLI。

- CLI 目标：`claude`、`codex`、`kimi`
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
python -m pytest tests -q
python -m pytest tests/test_cli.py tests/test_manager.py tests/test_sessions.py -q
python -m pytest tests/test_web_api.py tests/test_assistant.py tests/test_updater.py tests/test_release_assets.py -q
python -m pytest tests/test_plugin_manifest.py tests/test_plugin_service.py tests/test_plugin_runtime.py tests/test_vivado_waveform_plugin.py -q

# 前端测试 / 构建
cd front && npm test
cd front && npm test -- --run src/test/plugins-screen.test.tsx src/test/plugin-view-surface.test.tsx src/test/desktop-workbench.test.tsx
cd front && npm run build
cd front && npm run lint

# Agent Eval Suite
python -m pytest agent_eval_suite/tests/test_workspace_grader.py -q
python -m pytest tests/test_agent_eval_suite.py -q
python -m suite prepare --suite-root agent_eval_suite --run dry-hard --preset win-native-hard --samples 10 --overwrite
python -m suite score --suite-root agent_eval_suite --run dry-hard --evalplus-timeout 1.0
python -m suite report --suite-root agent_eval_suite --run dry-hard

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
├─ tests/                  # 后端 pytest 和 eval suite 集成测试
├─ agent_eval_suite/       # agent 评测套件
├─ examples/plugins/       # 示例插件
├─ docs/                   # 本地资料、计划和参考文档
├─ scripts/                # 辅助脚本
├─ deploy/                 # 发布/部署材料
├─ install.* / start.*     # 安装和启动脚本
├─ suite.py                # agent_eval_suite 仓库根入口
└─ AGENTS.md               # 本文件
```

不要提交或 force-add：

- `.env`
- `managed_bots.json`
- `docs/` 运行态资料和 release notes
- `agent_eval_suite/runs/`
- `agent_eval_suite/private_gold/<run>/`
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
- 旧 `webcli` 代码仅作兼容；manager 拒绝新 `webcli` bot，并把旧 profile 降级为 `cli`

## 核心区域

### Sessions 和 Chat History

`bot/sessions.py` 按 `(bot_id, shared_user_id, agent_id)` 存 session。Web user 通过 `bot/chat_identity.py:chat_session_user_id()` 归一化。

`UserSession` 跟踪当前工作目录、processing state、active subprocess、active conversation id、`codex` / `claude` / `kimi` / `native_agent` 原生 session id。

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
- 支持的 CLI 类型：`claude`、`codex`、`kimi`

关键行为：

- 用户文本以 `//` 开头时改写为 `/...`
- Codex 使用 JSON output，由 `parse_codex_json_output()` 解析
- Kimi 使用 streaming JSON，由 `parse_kimi_stream_json_output()` 解析
- 长 Web 回复在 Web API 层 streaming 和 finalize
- `execution_mode=native_agent` 使用 AG-UI 协议；普通 CLI legacy SSE 保持 `delta/status/trace/done`
- Pi runtime 只允许 `pi_session_runtime.py` 单 reader 读取 `client.events()`；工作区历史由本地 shadow git 处理，不再依赖 Pi `workspace_history` RPC
- Pi 会话绑定指纹固定为 `cwd + model_id + pi_agent + reasoning_effort`；任一项变化都要失效旧 session 和 workspace history rollback 链
- 普通 CLI trace 只进入 `ChatTracePanel`；只有原生来源使用 `NativeAgentTranscript`
- CLI SSE 的 `meta/status/trace/done` 顶层带 `turn_id`、`assistant_message_id`，用于前端稳定绑定当前轮
- CLI bot 可定义 child agents；非 cluster chat 只绑定一个 active agent，cluster mode 通过 `@agent_id` 分发 child agents

### Web API 和 Frontend

- 后端 API：`bot/web/server.py`、`bot/web/api_service.py`、`bot/web/git_service.py`
- 前端 app：`front/`
- 前端 screen 包括 chat、files、Git、terminal、debug、plugins、settings、assistant ops、admin center
- 已完成 assistant 回复用 Markdown 渲染，失败时 fallback 到 raw text
- plugin file view 支持 session-backed heavy views 和 VCD waveform rendering
- Git UI 支持 overview、diff、stage/unstage、commit、fetch/pull/push、stash/pop

## Agent Eval Suite

`agent_eval_suite/` 用于评测本地 coding agent。根目录 `suite.py` 是 shim；实际包在 `agent_eval_suite/suite/`。

关键文件：

- `suite/paths.py`：benchmark registry、run/workspace/private_gold 路径
- `suite/data.py`：`smoke`、`win-native`、`win-native-hard` 数据生成
- `suite/prepare.py`：写 `runs/<run>/workspace`、`tasks/`、`PROMPT.md`、`private_gold/<run>/`
- `suite/validation.py`：校验 answers JSONL schema
- `suite/scoring.py`：按 `manifest.enabled_benchmarks` 调 grader，写 `results.json`、`summary.csv`
- `suite/report.py`：写 `report.html`
- `suite/graders/workspace.py`：`workspace_ops` 文件态/命令评分器

生成目录：

```text
agent_eval_suite/runs/<run>/
  run.json
  manifest.json
  workspace/
    PROMPT.md
    tasks/*.jsonl
    answers/*.jsonl
    cases/<id>/          # hard preset
  report/
    results.json
    summary.csv
    report.html
agent_eval_suite/private_gold/<run>/*.jsonl
```

使用流程：

1. `python -m suite prepare --suite-root agent_eval_suite --run <run> --preset win-native-hard --samples 20`
2. 把 agent 工作目录设到 `agent_eval_suite/runs/<run>/workspace`
3. agent 只读 `tasks/` 和 `cases/`，写 `answers/`
4. `python -m suite score --suite-root agent_eval_suite --run <run> --evalplus-timeout 1.0`
5. `python -m suite report --suite-root agent_eval_suite --run <run>`

约束：

- `BENCHMARKS` 保持旧 4 项语义；hard preset 通过 `PRESET_BENCHMARKS` 加 `workspace_ops`
- 不要把 `private_gold`、hidden checks、oracle 写入 workspace
- `workspace_ops` 命令检查必须用 argv list，不用 shell 字符串
- 旧 `smoke` / `win-native` 仍只生成 IFEval、SimpleQA、EvalPlus、GAIA

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
