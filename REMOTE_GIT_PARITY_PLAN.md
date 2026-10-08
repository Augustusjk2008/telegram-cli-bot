# 远程与本地 Git 体验统一现状

## 目标与范围

远程工作区和本地工作区共用 Git 工作台、API 形状、错误语义和刷新规则。主机环境、凭据和网络造成的差异通过能力矩阵和服务端错误展示。

远程 Git 的状态、Diff、分支、提交和远端操作都以远程主机的 Git、文件系统、网络和凭据为准。本地控制目录不参与远程项目的读取、编辑或 Git 操作。

远程 Agent 的工作区历史回滚属于当前产品边界之外的能力。远程项目继续使用真实仓库历史，系统不会创建内部快照提交，也不会把本地 shadow Git 历史复制到远程主机。

## 当前实现

本地和远程通过 [`bot/web/git_backend.py:14`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/git_backend.py:14>) 使用同一组 Git backend 方法。统一路由位于 [`bot/web/routes/git_routes.py:8`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/routes/git_routes.py:8>)，远程命令由 [`bot/remote_workspace/git_service.py:81`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/remote_workspace/git_service.py:81>) 通过 SSH 在选定的远程仓库根目录执行。

Git capabilities 由 [`bot/git_contract.py:9`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/git_contract.py:9>) 定义。每项能力返回 `available`、`reason` 和 `requires_confirmation`；本地和远程使用相同的字段集合。

| 能力 | 本地 | 远程当前状态 |
| --- | --- | --- |
| 状态、初始化、Diff、逐文件暂存、取消暂存、手动提交 | 支持 | 支持 |
| Git 文件树状态 | 支持 | 支持 |
| 提交图、引用和分页 | 支持 | 支持 |
| 分支列表、创建、切换、重置 | 支持 | 支持 |
| 丢弃单文件或全部改动 | 支持 | 支持 |
| Stash 列表、应用、删除、弹出 | 支持 | 支持 |
| Stash 创建 | 支持 | 当前通过能力矩阵标记为不可用 |
| Git 用户身份读取和配置 | 支持 | 支持，配置写入远程仓库或远程用户配置 |
| Fetch、Pull、Push | 支持 | 支持，使用远程主机的仓库配置和凭据 |
| 提交说明生成、智能提交 | 支持 | 支持；Diff 从远程读取，提交在远程执行 |
| Agent 每轮工作区历史和回滚 | 支持 | 当前产品边界不包含 |

远程 Git 缺少时，能力矩阵返回 `remote_git_not_found`。远程仓库、上游分支或凭据不可用时，具体操作返回稳定错误码和诊断信息。Fetch、Pull、Push 使用 `GIT_TERMINAL_PROMPT=0`，避免等待交互式凭据输入；SSH 断线或超时后，服务端不会自动重放 mutation，响应会提示刷新状态。

远程 Pull 要求当前分支存在 upstream 且工作区干净，并使用 fast-forward only。远程 Push 写入当前分支的 upstream，远程 Fetch 使用 `--all --prune`。远程分支、Stash、丢弃改动和身份配置操作在执行前重新读取并校验引用、状态和路径。

远程智能提交的提交说明由服务端现有的本地 Agent 配置生成，输入来自远程工作区的状态和 Diff；暂存与提交仍通过远程 Git 服务完成。远程 Stash 创建暂未提供，前端展示服务端返回的不可用原因。

## 统一合约

Git 页面继续调用统一的 `/api/bots/{alias}/git/*` 接口。主要入口包括：

- `GET /capabilities`：读取能力矩阵。
- `GET /`：读取仓库概览、当前分支、Ahead / Behind、改动列表和近期提交。
- `GET /tree-status`：读取文件树的 Git 状态。
- `GET /graph`、`GET /branches`、`GET /stashes`、`GET /identity`：读取提交图、分支、Stash 和身份。
- `POST /branches`、`POST /branches/switch`、`POST /branches/reset`：执行分支操作。
- `POST /discard`、`POST /discard-all`：丢弃改动。
- `POST /stashes/apply`、`POST /stashes/drop`、`POST /stash/pop`：执行 Stash 操作。
- `PUT /identity`：更新远程或本地 Git 身份。
- `POST /fetch`、`POST /pull`、`POST /push`：执行远端同步。
- `POST /commit-message/generate`、`POST /smart-commit`：生成提交说明和执行智能提交。

Overview、Diff、状态截断、提交结果和错误响应保持相同字段语义。远程服务只复用纯解析器和响应模型；远程仓库的命令、路径和输出始终通过 SSH 执行。

## 安全与并发边界

- 远程根目录必须通过连接服务校验，Git 命令使用 exact path 或 exact ref，用户输入不会直接拼接成任意 shell 命令。
- 远程 Git mutation 使用按连接和 workspace root 共享的 Git 锁。
- Git 页面 mutation 在超时、断线、冲突和凭据失败后要求重新读取状态；服务端不会自动重试。
- Git 锁当前覆盖 Git backend 调用。Agent 的远程 `exec` 和独立终端仍可直接运行命令，workspace 级跨入口锁和冲突检测属于后续增强项。
- 远程工作区不提供语言服务、插件、调试和 workspace rollback。

## 当前已知差异

1. 远程 Stash 创建保持不可用，能力矩阵返回 `remote_feature_unavailable`。
2. 远程 Fetch、Pull、Push 的可用性还会受到远程仓库、upstream 和凭据状态影响，操作失败时显示服务端诊断。
3. Git 页面已接入能力矩阵；远程同步按钮保留远程工作区入口，具体远端状态由操作结果返回。
4. Git backend 锁尚未覆盖 Agent 远程命令和终端命令，自动避免跨入口覆盖仍需 workspace 级协调机制。
5. 远程 Git 的 Linux、Windows 和真实 SSH 网络场景仍需要实际远程主机验证。

## 验证

后端回归覆盖：

- [`tests/test_remote_git_service.py`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_remote_git_service.py>)：远程 Git 命令、路径、输出截断、Windows 参数、锁、错误诊断和 mutation 不重试。
- [`tests/test_remote_workspace_api.py`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_remote_workspace_api.py>)：认证、能力、远程路由和 profile 绑定。
- [`tests/test_git_service.py`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_git_service.py>)：本地和共享响应语义。
- [`tests/test_git_backend.py`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_git_backend.py>)：本地和远程 backend 委托及提交辅助。

前端回归覆盖：

- [`front/src/test/git-screen.test.tsx`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/git-screen.test.tsx>)：能力矩阵、按钮、错误和刷新行为。
- [`front/src/test/remote-git.spec.ts`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/remote-git.spec.ts>)：远程 Git API 边界、桌面和移动布局。该测试需要用户启动服务并设置 `PLAYWRIGHT_BASE_URL`。
- [`front/src/test/remote-workspace.test.tsx`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/remote-workspace.test.tsx>)：远程 workspace、路径和重连行为。

相关最小检查：

```powershell
python -m pytest tests/test_remote_git_service.py tests/test_remote_workspace_api.py tests/test_git_service.py tests/test_git_backend.py -q
cd front
npm run test:gate
npm run build
```

当前分支最近一次相关验证结果为后端 188 项通过、前端 498 项通过，生产构建和构建预算检查通过。真实远程 SSH 主机和 Playwright 场景需要在用户启动服务后单独执行。

## 后续增强

- 将远程同步按钮的展示和禁用状态完全绑定到能力矩阵与远程状态。
- 评估远程 Stash 创建的安全边界和交互确认。
- 设计覆盖 Git 页面、Agent 远程命令和终端的 workspace 级锁或冲突检测。
- 增加 Linux、Windows、凭据失败、网络中断、大 Diff 和异常文件名的真实远程回归。
