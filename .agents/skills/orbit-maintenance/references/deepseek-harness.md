# DeepSeek Harness CLI

## 配置与支持范围

- CLI 类型为 `deepseek`，默认执行命令为 `dsh`；主 Bot 和子 Bot 均可选择。配置入口是 `bot/config.py`、`bot/manager.py`、`bot/cli_params.py`。
- 当前支持本地工作区的 `execution_mode=cli`。原生执行模式、远程工作区、集群编排和 Git commit message 生成会在启动前拒绝；修改入口时保持前后端边界一致。
- 模型和 `reasoning_effort` 可在聊天页选择；空值或 `none` 继承 Harness 配置，思考深度支持 `off/low/high/max`。npm 安装的 dsh 通过每次调用的临时 patch 应用选择，保留原 provider 和其他配置；不修改用户的 Harness 配置。宿主 `extra_args` 仅接受 `--patch <文件路径>` 或 `--patch=<文件路径>`；协议参数、session id 和任务输入由宿主控制。
- 前端 CLI 标签和默认路径由 `front/src/utils/cliType.ts` 管理；执行模式入口见 `botManagerModel.ts`、`SettingsScreen.tsx`。设置页切换到 DeepSeek 时先关闭已启用的集群，再保存 CLI 配置。

## 执行协议

- `bot/cli_params.py:_build_deepseek_args()` 构造 `dsh --profile headless [--patch <path>] --json [--session-id <id>] -`，用户消息通过 stdin 发送；保留中文和多行输入。
- `bot/deepseek_cli.py` 识别 npm dsh 入口，由 `bot/deepseek_launch.mjs` 显式调用导出的 `runCli()`，兼容缺少 `import.meta.main` 的 Node 22.17。模型选择以最后一个临时 `--patch` 覆盖，进程正常退出时清理；自定义可执行文件保留原调用方式。
- `bot/cli.py:DeepSeekJsonStreamParser` 解析 stdout JSONL；`bot/web/api_service.py` 管理进程和轮次。stderr 独立收集，用于失败诊断。
- 成功需要有效 `session.sessionId`、`status.phase=turn_end` 且 `reason.kind=completed`、`final` 事件和进程退出码 0。无效 JSON、缺少结束事件、final 后继续输出运行事件或输出超限都必须保留失败状态。
- `text` 提供正文预览，`final.text` 替换最终正文。`thinking`、工具调用和工具结果进入 trace；保留 `callId` 配对与步骤去重。
- `status.phase=step_end` 用量按 `(turn, step)` 去重累加，只使用实际返回的字段；展示为本轮用量。

## 会话、历史与前端事件

- 会话沿用 `(bot_id, shared_user_id, agent_id)` 隔离；`deepseek_session_id` 由 `bot/models.py`、`bot/sessions.py`、`bot/session_store.py` 保存。只用 Harness 返回的 ID 续聊，新会话首次调用省略 `--session-id`。
- 历史、trace 和用量由项目 `ChatStore` 持久化；`bot/web/chat_history_service.py` 从选中 conversation 的 `native_session_id` 恢复绑定。DeepSeek 历史恢复不扫描外部 CLI 会话目录。
- trace 映射位于 `bot/web/native_history_adapter.py`。前端沿用 CLI `NativeAgentTranscript`，保持 legacy SSE `meta/status/trace/done` 及顶层 `turn_id`、`assistant_message_id`；增量正文位于 `status.preview_text`。
- 失败、停止和输出超限应保留已收到的正文，完成一次 turn 并释放 processing 状态；失败不得自动重放用户任务。

## 验证

协议、流式执行、会话恢复和 trace 变更运行：

```bash
python -m pytest tests/test_deepseek_exec.py tests/test_deepseek_history_adapter.py tests/test_cli_streaming.py -k deepseek -q
```

配置或持久化变更按需运行：

```bash
python -m pytest tests/test_manager.py tests/test_env_service.py tests/test_sessions.py tests/test_session_store.py -k deepseek -q
```

前端入口变更选择 `front/src/test/settings-screen.test.tsx`、`bot-manager-delete.test.tsx`、`real-client.test.ts` 中的相关用例；涉及布局时使用已启动的服务做 Playwright 检查。
