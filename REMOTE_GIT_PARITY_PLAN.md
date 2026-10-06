# 远程与本地 Git 体验统一路线图

## 目标

远程工作区和本地工作区使用同一套 Git 工作台、API 形状和交互语义。主机环境、凭据和网络造成的差异通过能力矩阵明确展示，不通过前端硬编码隐藏功能，也不把“不支持”伪装成成功。

这里的“统一”分为三个层次：

1. 用户看到相同的 Git 页面、变更分组、Diff、提交、分支和远端操作入口。
2. 前后端使用相同的请求、响应、错误码和刷新规则。
3. Agent 在远程工作区中具备接近本地的 Git 操作和工作区历史能力。

底层环境不可能完全相同。远程 Git 必须以远程主机的 Git、文件系统、网络和凭据为准；本地控制目录不能参与远程项目的读取、编辑或 Git 操作。

## 当前状态

当前已经共享 `GitScreen` 和 `WebBotClient` 的大部分 Git 数据结构，但远程实现仍是第一阶段能力：

| 能力 | 本地 | 远程当前状态 |
| --- | --- | --- |
| 状态、初始化、Diff、逐文件暂存、取消暂存、提交 | 支持 | 支持 |
| 丢弃单文件或全部改动 | 支持 | 不支持 |
| 分支列表、创建、切换、重置 | 支持 | 不支持 |
| 提交图和 Git 文件树状态 | 支持 | 不支持 |
| Stash 列表、应用、删除 | 支持 | 不支持 |
| Fetch、Pull、Push | 支持 | 不支持 |
| Git 用户身份 | 支持 | 不支持 |
| 提交说明生成、智能提交 | 支持 | 不支持 |
| Agent 每轮工作区历史和回滚 | 支持 | 当前关闭 |

远程 Git 服务位于 [`bot/remote_workspace/git_service.py:67`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/remote_workspace/git_service.py:67>)，当前远程路由只注册 overview、init、diff、stage、unstage 和 commit，见 [`bot/web/routes/remote_routes.py:25`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/routes/remote_routes.py:25>)。本地路由已经覆盖完整 Git 工作台，见 [`bot/web/routes/git_routes.py:8`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/routes/git_routes.py:8>)。

前端目前通过 `remote` 条件直接隐藏分支、远端、Stash、智能提交等区域，见 [`front/src/screens/GitScreen.tsx:1274`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/GitScreen.tsx:1274>) 和 [`front/src/screens/GitScreen.tsx:1492`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/GitScreen.tsx:1492>)。远程工作台也主动跳过 Git 文件树状态刷新，见 [`front/src/workbench/DesktopWorkbench.tsx:509`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/DesktopWorkbench.tsx:509>)。

远程 Agent 的项目操作通过 `tcb-remote` 的 SSH 工具执行，见 [`bot/remote_workspace/chat.py:142`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/remote_workspace/chat.py:142>)。本地 Agent 的 shadow Git 工作区历史不能直接复用到远端；远程回滚当前明确关闭，见 [`bot/native_agent/service.py:578`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/native_agent/service.py:578>)。

## 设计原则

- **能力驱动。** 前端根据服务端返回的能力和原因渲染、禁用或提示功能，避免用 `remote` 判断代替真实能力。
- **远程源为准。** 远程 Git 的状态、Diff、身份、分支和提交都从远程仓库读取；本地控制目录不保存远程仓库内容和凭据。
- **变更不自动重试。** SSH 断线或超时后，提交、Push、Stash 等 mutation 可能已经生效，必须让用户重新读取状态后决定下一步。
- **保持用户仓库干净。** Agent 的内部快照不能悄悄创建用户可见的真实 Git 提交。
- **安全边界不放宽。** 继续遵守已确认的 SSH host key、远程 workspace root、能力权限、路径校验和输出上限。

## 实施步骤

### 1. 固化统一 Git 合约

在 Git overview 中增加服务端能力信息，或者提供独立的 `/git/capabilities` 接口。为每个能力返回至少：

```json
{
  "available": true,
  "reason": "",
  "requires_confirmation": false
}
```

建议首先覆盖：

- `tree_status`
- `commit_graph`
- `branches`
- `branch_mutation`
- `discard`
- `stash`
- `identity`
- `fetch`
- `pull`
- `push`
- `commit_message_generation`
- `smart_commit`

同时统一以下行为：仓库根目录、当前分支、Ahead / Behind、未跟踪文件、Diff 截断、提交结果、错误码和刷新策略。

### 2. 统一本地和远程后端入口

保留现有本地 Git 实现，增加本地和远程都遵守的 Git backend 接口或 facade。路由层根据 profile 是否绑定远程工作区选择 backend，前端仍然调用同一批 `/git/*` 请求。

远程 `RemoteGitService` 逐步补齐本地服务已有的操作。公共部分只复用纯解析器和响应模型，不能让远程实现访问本地项目目录，也不能把本地 subprocess 逻辑误用于远程仓库。

### 3. 先完成只读能力

优先实现远程：

1. `tree-status`，让远程文件树显示 Git 状态。
2. 分支列表和当前分支。
3. 提交图、引用和分页。
4. Stash 列表。
5. Git 身份读取。
6. Ahead / Behind 和完整的提交详情。

这一阶段主要验证远程 Git 输出解析、分页、路径编码和 SSH 往返延迟，不涉及大量破坏性 mutation。

### 4. 补齐安全的写操作

实现远程：

- 丢弃单文件和全部改动。
- 创建、切换和重置分支。
- Stash apply、drop 和 pop。
- Git 全局及仓库级身份配置。

每项操作都需要：

- 在远程执行前重新校验当前状态或引用。
- 使用 exact path 或 exact ref，禁止把用户输入拼成任意 shell 命令。
- 使用按连接和 workspace root 共享的 Git 锁。
- 对 dirty worktree、detached HEAD、冲突和目标不存在返回明确错误。

### 5. 实现 Fetch / Pull / Push

远程 Git 当前通过 `GIT_TERMINAL_PROMPT=0` 禁止交互式凭据提示，见 [`bot/remote_workspace/git_service.py:42`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/remote_workspace/git_service.py:42>)。因此需要先确定远程凭据方案：

- 远程主机 SSH agent。
- 远程主机 credential helper。
- 远程仓库使用已配置的 SSH URL。
- 明确的远程 token 或 askpass 机制。

Git 工作台应提供凭据不可用的诊断，而不是等待命令超时。Pull、Push 需要明确用户操作和确认；断线后只刷新状态，不自动重放命令。

### 6. 让前端完全使用能力矩阵

逐步移除 `GitScreen` 中按 `remote` 隐藏功能的分支：

- 能力可用时显示与本地相同的组件。
- 能力不可用时显示禁用状态和服务端原因。
- 只有真正依赖本地 Agent 或本地 CLI 的功能，才保留明确的本地限制。
- 远程 workspace 切换、重连、文件编辑和 Git 页面刷新使用同一 workspace identity。

这样可以避免前端请求边界和后端能力长期不一致。

### 7. 单独设计远程 Agent 工作区历史

本地 shadow Git 历史记录在服务端本地数据目录中，使用独立的 bare Git 存储；远程不能直接把远程项目复制到本地再操作。

如果要实现远程每轮回滚，需要新增远程历史 backend，并确定：

- 快照存放在远程 workspace 外还是受控的远程数据目录。
- 快照与 conversation、agent、model、cwd 的绑定方式。
- 文件数量、单文件大小、总容量和扫描超时预算。
- 远程 workspace 删除、profile 归档和 SSH 失效后的清理策略。
- Agent、Git 工作台和终端同时修改时的并发规则。

在这些问题确定前，远程回滚应继续明确显示为不可用，不应把真实仓库提交当作内部快照。

## 主要难点

### 远程命令语义

远程 Git 通过 SSH 执行，Linux 使用 shell，Windows 使用 PowerShell 和原生进程启动。参数引号、反斜杠、大小写、换行、符号链接、Git 版本和 hook 行为都可能与本地不同。远程当前还要求 workspace root 必须等于仓库根目录，见 [`bot/remote_workspace/git_service.py:104`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/remote_workspace/git_service.py:104>)。

### 凭据和网络

本地 Push / Pull 可以使用本机 Git 配置和代理；远程操作使用远程主机的网络和 credential helper。SSH 连接成功不代表远程 Git remote 的 HTTPS 或 SSH 凭据可用。

### 失败后的状态不确定

SSH 断线可能发生在远程 Git 已经提交之后。传输层当前也明确不会自动重试，见 [`bot/remote_workspace/transport.py:141`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/remote_workspace/transport.py:141>)。所有 mutation 都需要状态刷新和幂等性说明。

### 并发操作

Git 工作台的锁不能自动约束 Agent 通过远程 `exec` 或终端运行的 Git 命令。需要决定是否引入 workspace 级操作锁、短租约或冲突检测，否则分支切换、提交和 Agent 编辑可能互相覆盖。

### 性能和输出限制

远程 overview 可能需要多次 SSH 命令，Diff 和 status 还受到远程输出上限影响。需要使用分页、短期缓存、明确的截断字段和大仓库验证，不能把本地 Git 的响应时间假设直接搬到远程。

### 智能提交的执行位置

本地提交说明生成使用本地 CLI 配置和本地 Git Diff。远程智能提交需要决定由服务端生成、由远程 Agent 生成，还是只支持人工提交，并确保生成过程读取的是远程 Diff。

## 里程碑

### M0：契约和能力矩阵

- 定义统一 overview、capabilities 和错误码。
- 定义各 Git mutation 的确认、锁和失败后刷新规则。
- 不改变现有远程功能。

### M1：可见体验统一

- 远程支持 tree-status、分支读取、提交图、Stash 读取、身份读取。
- 远程支持丢弃、分支基本操作、Stash 基本操作和身份配置。
- 前端改为能力驱动。
- 本地和远程使用相同的变更、Diff、分支和提交布局。

### M2：远端同步和提交辅助

- 实现远程 Fetch、Pull、Push。
- 完成远程凭据诊断和确认流程。
- 评估并实现远程提交说明生成或智能提交。

### M3：Agent 工作区历史

- 实现远程 shadow history backend，或正式记录远程回滚不在支持范围内的产品边界。
- 增加容量、并发、连接失效和 profile 生命周期测试。

## 验证矩阵

后端重点覆盖：

- [`tests/test_remote_git_service.py`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_remote_git_service.py>)：远程 Git 命令、路径、输出截断、Windows 参数、锁和 mutation 不重试。
- [`tests/test_remote_workspace_api.py`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_remote_workspace_api.py>)：认证、能力、远程路由和 profile 绑定。
- [`tests/test_git_service.py`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_git_service.py>)：本地和共享响应语义不被破坏。

前端重点覆盖：

- [`front/src/test/git-screen.test.tsx`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/git-screen.test.tsx>)：本地和远程能力矩阵、按钮、错误和刷新行为。
- [`front/src/test/remote-git.spec.ts`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/remote-git.spec.ts>)：真实远程 API 的桌面和移动布局、请求边界及异常状态。
- [`front/src/test/remote-workspace.test.tsx`](</C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/remote-workspace.test.tsx>)：远程 workspace、路径和重连行为。

实现每个里程碑后运行最小相关检查：

```powershell
python -m pytest tests/test_remote_git_service.py tests/test_remote_workspace_api.py tests/test_git_service.py -q
cd front
npm run test:gate
npm run build
```

涉及真实远程 Git UI 时，再运行用户启动服务后的 Playwright 检查：

```powershell
cd front
npx playwright test src/test/remote-git.spec.ts
```

## 验收标准

- 本地和远程 Git 页面在能力相同的情况下具有相同的操作入口、状态、Diff 和刷新行为。
- 不可用能力显示准确原因，不出现本地路径、控制目录或本地凭据泄露。
- 远程 mutation 在超时、断线、冲突和凭据失败时不会自动重放。
- Agent、终端和 Git 页面并发操作时不会静默覆盖彼此的变更。
- 远程 Linux、远程 Windows、本地 Windows、无仓库、空仓库、dirty worktree、大 Diff 和异常文件名均有回归覆盖。
- Agent 工作区历史与用户真实仓库历史保持清晰分离。
