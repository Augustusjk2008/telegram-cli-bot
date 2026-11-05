# Remote Workspace、Terminal 与 Git

## 入口和边界

- SSH 连接、主机密钥确认、远程路径解析和连接池：`bot/remote_workspace/transport.py`、`windows.py`。
- Agent 远程工具、profile capability、loopback bridge 和 Pi 扩展：`bot/remote_workspace/chat.py`、`mcp_stdio.py`、`pi_extension.ts`、`tools.py`。
- Web 文件、目录和远程执行：`bot/web/routes/remote_routes.py`；统一 Git 后端与远端操作：`bot/web/git_backend.py`、`bot/remote_workspace/git_service.py`。
- Web terminal：`bot/web/terminal_manager.py`、`bot/web/routes/terminal_routes.py`。

## 必须保持的行为

- SSH 首次连接接受系统已知 host key，未知密钥要求确认指纹；已绑定指纹变化必须拒绝。密码和私钥口令只保留在连接对象内存中，关闭连接时清除。
- 已绑定工作区的文件 API 和 `exec.cwd` 校验 workspace root；连接向导可浏览远端目录以选择 root。远程 shell 按 SSH 账户权限执行，路径校验与工具路由不提供进程级文件系统沙箱。
- POSIX 命令使用 `/bin/sh`；Windows 命令使用 `powershell.exe`，需兼容 PowerShell 5.1。Windows 文件 API 规范化盘符路径并拒绝 UNC/device 路径、junction 和 symlink。
- Agent 的远程项目操作必须经过 `tcb-remote` 的 `exec/read/write/edit/list` 工具。bridge 只允许连接已有 Web 服务的 loopback 地址，工具参数和输出有大小上限；可能已经执行的 mutation 不得自动重试。
- 远程 capability 绑定 profile alias 和 `remote_workspace` fingerprint；接口还校验当前 profile 是否启用、归档、控制目录或远端配置是否变化。移除 profile 时撤销绑定，旧 token 不得转指新目标。私有 bridge 配置位于 `get_app_data_root()/remote-chat/`。
- Codex（含 `codex_server`）和 Claude 通过启动参数注入 stdio MCP；Pi 使用 `TCB_REMOTE_MCP_CONFIG` 和 `--no-builtin-tools --extension`。仅 Antigravity 写入控制目录的 `.agents/mcp_config.json`，配套 ownership state、跨进程锁和原子写入；保留用户服务器与用户修改过的 `tcb-remote` 条目，冲突时报错，撤销只清理本 profile 仍拥有的条目。DeepSeek Harness 只支持本地工作区；远程 Antigravity 暂不支持 Cluster 编排。
- Pi 扩展提供 `remote_*` 工具以及兼容别名 `read`、`write`、`ls`、`edit`、`bash`。项目读取、编辑、搜索和测试在远端完成；聊天附件存放在本地控制目录 `attachments/`，Pi 的 `local_read`、`local_bash` 用于处理这些附件，输出留在附件旁。
- `exec.commands` 支持批量命令；`edit` 要求 `old_text` 恰好匹配一次，并按读取到的文件版本做乐观并发校验。
- 远程 Git 使用远端 workspace root 和对应 Web capability；支持状态、diff、分支、图、暂存、提交、身份配置、已有 stash 操作和 fetch/pull/push，具体可用性以 capabilities 为准，当前不支持创建 stash。智能提交把远端 diff 交给本地 agent 生成提交信息，Git 操作仍在远端执行。
- Git 同步错误保留 `operation`、`outcome`、`refresh_required`；网络中断可能返回 `outcome=unknown`，mutation 不自动重试。`pull` 使用 `--ff-only` 并要求干净工作区和 upstream。
- Terminal session 按 `(user_id, owner_id)` 隔离；每个 tab 使用独立 `owner_id`，关闭 tab 必须关闭对应 shell，WebSocket detach 只移除客户端并保留会话以便重连。远程 tab 使用独立 SSH channel。`/api/bots/{alias}/terminal/session/rebuild` 和无 alias 的 rebuild 路由保留为兼容创建入口。

## 验证

- SSH、主机密钥、路径边界和连接池：`tests/test_remote_workspace_transport.py`、`tests/test_remote_workspace_windows.py`。
- 远程 API、附件、agent tools 和 profile 绑定：`tests/test_remote_workspace_api.py`；capability、MCP 配置归属、CLI/Pi 注入及会话失效：`tests/test_remote_workspace_chat.py`。
- 远程 Git：`tests/test_remote_git_service.py`。
- Terminal 生命周期、owner 隔离、重连和 WebSocket 协议：`tests/test_terminal_manager.py`、`front/src/test/terminal-session.test.ts`。
- 涉及远程文件或 Git UI 时选择 `front/src/test/remote-workspace.test.tsx`、`front/src/test/remote-git.spec.ts` 及相应前端检查；浏览器测试复用用户已启动的服务。
