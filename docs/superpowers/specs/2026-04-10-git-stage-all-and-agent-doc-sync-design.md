# Git Stage-All And Agent Doc Sync Design

日期：2026-04-10

## 目标

为 Web Bot 的 Git 页面增加一个“暂存全部”按钮，用于一次性暂存所有未暂存和未跟踪文件；同时把项目根目录的 `AGENTS.md` 更新为当前代码实际状态，并将同内容同步到 `CLAUDE.md`。

## 用户确认的约束

- “暂存全部”按钮放在 Git 页面“提交更改”按钮旁边。
- 该按钮只处理未暂存和未跟踪文件，不改变已暂存文件状态。
- 优先复用现有前后端 Git 接口，不新增专用 `stage all` API。
- `AGENTS.md` 以当前代码实际状态为准进行修正。
- `CLAUDE.md` 最终内容与更新后的 `AGENTS.md` 保持一致。

## 现状

- [front/src/screens/GitScreen.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/GitScreen.tsx) 当前支持单文件“暂存”“取消暂存”和“提交更改”，但没有批量暂存入口。
- [front/src/services/webBotClient.ts](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/webBotClient.ts) 以及其真实 / mock 实现已经提供 `stageGitPaths(botAlias, paths)`，接口签名本身支持一次传入多个路径。
- [bot/web/git_service.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/git_service.py) 的 `stage_git_paths()` 已使用 `git add -- <paths...>`，说明后端已经具备批量暂存能力。
- [front/src/test/git-screen.test.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/git-screen.test.tsx) 当前覆盖 Git 概览、初始化仓库等基础行为，但未覆盖 Git 页面批量暂存入口。
- [AGENTS.md](C:/Users/JiangKai/telegram_cli_bridge/refactoring/AGENTS.md) 与 [CLAUDE.md](C:/Users/JiangKai/telegram_cli_bridge/refactoring/CLAUDE.md) 当前内容不一致，且前者仍保留部分过时描述。

## 方案

- 在 Git 页面提交区新增“暂存全部”按钮，与“提交更改”并排展示。
- 按钮点击时收集 `unstaged` 和 `untracked` 两组文件的路径，合并后调用现有 `client.stageGitPaths(botAlias, paths)`。
- 不新增后端接口，也不改 `WebBotClient` 类型定义，因为现有方法已满足需求。
- 成功后沿用当前 `runAction()` 的 `notice` 与 `overview` 刷新逻辑，保持 Git 页面状态更新方式一致。
- 文档方面不做“同步脚本”自动化，本次直接以当前代码实态重写 `AGENTS.md`，再将同文本覆盖到 `CLAUDE.md`。

## UI 与交互设计

- “暂存全部”按钮位于提交区，与“提交更改”横向排列，视觉层级低于主提交按钮，可使用边框按钮样式。
- 当未暂存和未跟踪文件总数为 0 时，按钮禁用。
- 当任意 Git 动作正在执行时，按钮与现有 Git 操作按钮保持同样的禁用策略。
- 点击后按钮进入加载态，文案可显示为“暂存中...”。
- 若批量暂存成功，沿用现有提示条显示结果消息。

## 数据与行为边界

- 批量暂存的目标路径集合定义为：`groups.unstaged + groups.untracked`。
- 已暂存文件不重复提交给 `stageGitPaths()`。
- 若某个文件同时处于 staged + unstaged 的混合状态，只应把其工作区变更再次纳入暂存；现有 Git 语义通过对该路径再次执行 `git add` 已满足这一点。
- 若路径集合为空，则前端直接禁用按钮，不额外触发请求。

## 文档更新范围

- `AGENTS.md` / `CLAUDE.md` 需要反映当前代码实态：
  - 项目是 Windows 优先的 Telegram CLI Bridge
  - Telegram 运行时当前活跃 bot_mode 为 `cli` 与 `assistant`
  - 遗留 `webcli` 代码仍在仓库，但注册逻辑已回退为 CLI，不应再描述为当前主路径
  - 管理命令包含 `/system`、`/bot_params*`、`/bot_kill`
  - 语音依赖缺失时会跳过语音处理器
  - Web 前端存在 Git、文件、设置、聊天等页面与对应测试
- 两份文档内容最终保持一致，不再保留互相冲突的表述。

## 测试

- 新增前端测试覆盖 Git 页面“暂存全部”按钮的显示与调用参数。
- 新增前端测试覆盖当只有已暂存文件时，“暂存全部”按钮处于禁用状态。
- 保留现有 Git 页面测试，确保仓库概览、初始化仓库等行为不回归。
- 文档同步无需自动化测试，但应通过 diff 人工核对 `AGENTS.md` 与 `CLAUDE.md` 内容完全一致。
