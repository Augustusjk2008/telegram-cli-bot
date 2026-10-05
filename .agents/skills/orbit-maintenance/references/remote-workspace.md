# Remote Workspace、Terminal 与 Git

## 入口和边界

- SSH 连接、主机密钥确认、远程路径解析和连接池：`bot/remote_workspace/transport.py`、`windows.py`。
- Agent 远程工具、profile capability、loopback bridge 和 Pi 扩展：`bot/remote_workspace/chat.py`、`mcp_stdio.py`、`pi_extension.ts`、`tools.py`。
- Web 文件、目录、远程执行和 Git 路由：`bot/web/routes/remote_routes.py`、`bot/remote_workspace/git_service.py`。
- Web terminal：`bot/web/terminal_manager.py`、`bot/web/routes/terminal_routes.py`。

## 必须保持的行为

- 远程 profile 只能通过已确认的 SSH host key 连接；远程路径必须限制在绑定的 workspace root 内，并遵守目标平台的路径规则。
- Agent 的远程项目操作必须经过 `tcb-remote` 的 `exec/read/write/edit/list` 工具。bridge 只允许连接已有 Web 服务的 loopback 地址，工具参数和输出有大小上限；可能已经执行的 mutation 不得自动重试。
- 远程 capability 绑定 profile fingerprint；profile 被修改或归档后必须拒绝旧 token，并在移除 profile 时撤销绑定。Pi 使用 `TCB_REMOTE_MCP_CONFIG`，Codex/Claude 使用同一 profile 的 stdio 配置。
- Pi 扩展提供 `remote_*` 工具以及兼容别名 `read`、`write`、`ls`、`edit`、`bash`；远程 profile 的本地目录只是控制目录，项目读取、编辑、搜索和测试都在远端完成。
- 远程 Git 操作必须使用远端 workspace root 和对应 Web capability；不要把远端仓库内容或凭据写入本地项目目录。
- Terminal session 按 `(user_id, owner_id)` 隔离；每个 tab 使用独立 `owner_id`，关闭 tab 必须关闭对应 shell。`/api/bots/{alias}/terminal/session/rebuild` 和无 alias 的 rebuild 路由是兼容创建入口，不得改变其语义。

## 验证

- SSH、主机密钥、路径边界和连接池：`tests/test_remote_workspace_transport.py`、`tests/test_remote_workspace_windows.py`。
- 远程 API、capability、agent tools 和 profile 绑定：`tests/test_remote_workspace_api.py`。
- 远程 Git：`tests/test_remote_git_service.py`。
- Terminal 生命周期、owner 隔离、重连和 WebSocket 协议：`tests/test_terminal_manager.py`、`front/src/test/terminal-session.test.ts`。
- 涉及远程文件或 Git UI 时运行 `front/src/test/remote-workspace.test.tsx`、`front/src/test/remote-git.spec.ts` 及前端 test gate/build。
