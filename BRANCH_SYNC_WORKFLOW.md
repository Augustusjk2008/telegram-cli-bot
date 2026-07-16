# 原始仓库与 Feature 分支同步流程

本文记录本仓库的固定分支策略：本地 `master` 始终与真实原始仓库的
`origin/master` 保持一致，开发特性只保存在 feature 分支，并由 feature
分支主动合入最新 `master`。

## 分支与远端约定

- 原始仓库：`https://github.com/Augustusjk2008/telegram-cli-bot.git`
- 原始仓库远端名：`origin`
- 原始仓库主分支：`master`（不是 `main`）
- 当前特性分支：`feature/runtime-terminal`
- `fork` 只用于访问 Fork 仓库，不作为 `master` 的同步来源

目标拓扑：

```text
origin/master ── local master
                    \
                     feature/runtime-terminal
```

## 同步前检查

先确认远端和工作区状态：

```bash
cd /home/lightby/apps/telegram-cli-bot

git remote set-url origin https://github.com/Augustusjk2008/telegram-cli-bot.git
git remote -v
git status
git branch -vv
```

如果 feature 分支有未提交改动，推荐先提交。暂时不准备提交时，可先暂存：

```bash
git switch feature/runtime-terminal
git stash push -u -m "wip-feature-before-master-sync"
```

## 更新本地 master

只允许从 `origin/master` 快进本地 `master`：

```bash
git switch master
git fetch origin --prune
git merge --ff-only origin/master
```

`--ff-only` 如果失败，说明本地 `master` 含有不属于原始仓库的提交。此时不要
把 feature 合入 `master`，也不要直接强制推送。按“恢复误合并的 master”处理。

## 将 master 合入 feature

更新 `master` 后，切回 feature 分支，并从 feature 一侧合入 `master`：

```bash
git switch feature/runtime-terminal
git merge --no-ff master \
  -m "merge: sync latest master into feature"
```

若此前使用了 stash，在合并成功后恢复：

```bash
git stash list
git stash pop stash@{0}
```

恢复前先确认 `stash@{0}` 的说明是 `wip-feature-before-master-sync`，避免误取更早的
stash。

## 处理合并冲突

发生冲突时保持在 feature 分支：

```bash
git status
rg -n "^(<<<<<<<|=======|>>>>>>>)" <冲突文件>
```

编辑并验证冲突文件后完成合并：

```bash
git add <已解决文件>
git diff --cached --check
git commit --no-edit
```

按改动范围运行相应测试；完整门禁命令为：

```bash
python -m pytest tests -q
cd front && npm run test:gate
cd front && npm run build
cd front && npm run lint
```

## 恢复误合并的 master

如果误在 `master` 上合入了 feature，先切到 feature 并保留正确的特性提交，再把
`master` 指回原始远端：

```bash
git switch feature/runtime-terminal
git branch backup/master-before-realign master
git branch -f master origin/master
```

确认恢复结果：

```bash
git rev-parse master
git rev-parse origin/master
git merge-base --is-ancestor master feature/runtime-terminal
git branch -vv
git log --graph --oneline --decorate -10 --all
```

前两个提交哈希应完全一致，`merge-base --is-ancestor` 应返回退出码 `0`。

## 禁止的同步方向

不要在 `master` 分支执行：

```bash
git merge feature/runtime-terminal
```

也不要将 Fork 仓库作为 `master` 的拉取来源。正确方向始终是：

```text
origin/master -> local master -> feature/runtime-terminal
```

除非明确要向原始仓库发布，否则不要执行 `git push origin master`。
