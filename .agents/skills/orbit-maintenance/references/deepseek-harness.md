# DeepSeek Harness CLI

## 配置与支持范围

- CLI 类型为 `deepseek`，默认执行命令为 `dsh`；主 Bot 和子 Bot 均可选择。配置入口是 `bot/config.py`、`bot/manager.py`、`bot/cli_params.py`。
- 当前支持本地工作区的 `execution_mode=cli`，包括 Bot 级 TCB 集群编排。原生执行模式、远程工作区和 Git commit message 生成会在启动前拒绝；修改入口时保持前后端边界一致。
- 模型和 `reasoning_effort` 可在聊天页选择；空值或 `none` 继承 Harness 配置，思考深度支持 `off/low/high/max`。DeepSeek Harness 必须使用桌面版 `resources\runtime\cli\bin\dsh.cmd`，每次调用通过桌面版内置 Electron 和 dsh 包的临时 patch 应用选择；桌面 profile 中的模型路由、`llm-pi-ai`、`llm-deepseek` 以及 credentials 服务 patch 会临时桥接到 headless profile，使桌面端配置的 provider（例如 `opencode-go`）和凭据环境变量映射继续生效。npm shim 与 `DeepSeek Harness.exe` GUI 路径会被拒绝，不修改用户的 Harness 配置。宿主 `extra_args` 仅接受 `--patch <文件路径>` 或 `--patch=<文件路径>`；协议参数、session id 和任务输入由宿主控制。
- `permission_mode` 支持 `read-only/workspace-write/danger-full-access`，默认 `workspace-write`，通过 `DSH_PERMISSION_MODE` 传给 Harness。Web 调用通过 `clamp_unsafe_cli_params()` 限制未获 `allow_unsafe_cli` 的 `danger-full-access`；集群 `allow_write` 不替代这层 CLI 权限配置。
- 前端 CLI 标签和默认路径由 `front/src/utils/cliType.ts` 管理；执行模式入口见 `front/src/screens/botManagerModel.ts`、`SettingsScreen.tsx`。设置页切换到 DeepSeek 时先保存 CLI 执行模式，再保存 CLI 类型和路径，保留 Bot 的集群开关。

## 本地集群接入

- `bot/web/api_service.py:_cluster_mcp_injected_params()` 调用 `write_deepseek_mcp_patch()`，向 DeepSeek 参数块追加 `--patch <path>`。`bot/cluster/setup.py` 生成包含 `@deepseek-ai/dsh-mcp-client` 的 patch，以当前 Python 执行项目 `bot/cluster/mcp_stdio.py --config <bridge-config>`，传入工作区 cwd，并设置 `failOnStartupError=true`。
- patch 由宿主管理，位于 cluster MCP 配置目录；管理页准备该文件，DeepSeek 的 MCP 安装、验证、移除命令列表均为空。接入不修改用户 Harness 全局配置。
- 工具、显式 `run_id` 和编组规则沿用 [native-agent.md](native-agent.md) 的公共 MCP 契约。CLI 子任务的模型档位映射到 DeepSeek 的 `model` 和 `reasoning_effort`。

## 执行协议

- `bot/cli_params.py:_build_deepseek_args()` 构造 `dsh --profile headless [--patch <path>] --json [--session-id <id>] -`，用户消息通过 stdin 发送；保留中文和多行输入。
- `bot/deepseek_cli.py` 解析桌面版 `dsh.cmd` 中的 Electron 与 `dsh-desktop-host` 路径，由 `bot/deepseek_launch.mjs` 在 Electron Node 模式中加载桌面版内置 dsh 的 `runCli()` 与 profile 组合逻辑，兼容缺少 `import.meta.main` 的运行时。模型选择在已有 patch（含集群 patch）后追加临时 `--patch`，保留合并后的 provider 配置，退出回调清理临时文件。启动器在 JSON 模式通过 `orbit_model` 元数据报告显式选择或继承的模型名，用于费用估算；默认模型配置无法静态读取时跳过该元数据。npm shim 与 GUI exe 不作为后备入口。
- `bot/cli.py:DeepSeekJsonStreamParser` 解析 stdout JSONL；`bot/web/api_service.py` 管理进程和轮次。stderr 独立收集，用于失败诊断。
- Windows 上 dsh 进程使用 breakaway 启动并跳过 Orbit Job Object containment，避免嵌套 job 干扰 Harness 自己的进程隔离；修改统一 CLI 进程生命周期时保留该分支。
- 成功需要有效 `session.sessionId`、`status.phase=turn_end` 且 `reason.kind=completed`、`final` 事件和进程退出码 0。无效 JSON、缺少结束事件、final 后继续输出运行事件或输出超限都必须保留失败状态。
- `text` 提供正文预览，`final.text` 替换最终正文。`thinking`、工具调用和工具结果进入 trace；保留 `callId` 配对与步骤去重。
- `status.phase=step_end` 用量按 `(turn, step)` 去重累加，仅汇总各步骤共同具备的字段；缺少用量或计数无效的步骤会使完整用量不可用。`bot/web/cli_context_usage.py` 还能按当前 session id 读取 `DSH_HOME`（默认 `~/.dsh`）下的 `contextPressure` projection；`_build_deepseek_context_usage()` 合并会话上下文占用和本轮用量，缺少 projection 时显示本轮用量。每轮结束附加并持久化 `scope=turn` 的费用估算，Harness 普通输入已排除缓存，reasoning 已包含在输出中；失败或中断时可计价的已上报用量标记为部分估算。模型未知或用量不完整时不显示费用。默认 CSV 为 Flash 和 Pro 配置 CNY 人民币高峰固定单价，不自动套用空闲时段折扣。

## 会话、历史与前端事件

- 会话沿用 `(bot_id, shared_user_id, agent_id)` 隔离；`deepseek_session_id` 由 `bot/models.py`、`bot/sessions.py`、`bot/session_store.py` 保存。只用 Harness 返回的 ID 续聊，新会话首次调用省略 `--session-id`。
- 历史、trace 和用量由项目 `ChatStore` 持久化；`bot/web/chat_history_service.py` 从选中 conversation 的 `native_session_id` 恢复绑定。DeepSeek 历史恢复不扫描外部 CLI 会话目录。
- trace 映射位于 `bot/web/native_history_adapter.py`。前端沿用 CLI `NativeAgentTranscript`，保持 legacy SSE `meta/status/trace/done` 及顶层 `turn_id`、`assistant_message_id`；增量正文位于 `status.preview_text`。
- 失败、停止和输出超限应保留已收到的正文，完成一次 turn 并释放 processing 状态；失败不得自动重放用户任务。

## 验证

协议、流式执行、会话恢复和 trace 变更运行：

```bash
python -m pytest tests/test_deepseek_exec.py tests/test_deepseek_history_adapter.py tests/test_cli_streaming.py tests/test_cli_context_usage.py tests/test_model_pricing.py -k deepseek -q
```

集群接入、配置或持久化变更按需运行：

```bash
python -m pytest tests/test_cluster_setup.py tests/test_manager.py tests/test_env_service.py tests/test_sessions.py tests/test_session_store.py -k deepseek -q
```

前端入口变更选择 `front/src/test/settings-screen.test.tsx`、`bot-manager-delete.test.tsx`、`real-client.test.ts` 中的相关用例；涉及布局时使用已启动的服务做 Playwright 检查。
