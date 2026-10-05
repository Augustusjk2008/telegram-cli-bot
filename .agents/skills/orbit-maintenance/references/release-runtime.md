# 安装、运行态与发布

## 入口

- Windows 安装：`install.bat`、`install.ps1`；启动：`start.bat`、`start.ps1`。
- Linux/macOS 安装：`install.sh`；启动：`start.sh`。
- `bot/__main__.py` 调用 `bot/main.py:main()`；`main()` 在 restart loop 中执行 `asyncio.run(run_all_bots())`。
- `/restart` 设置 `config.RESTART_REQUESTED`、`config.RESTART_EVENT` 后 re-exec。

## 发布

```powershell
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree -ReleaseNotesFile .\docs\release-notes\v<version>.md
```

- 自动更新只检查 GitHub Releases。
- Release body 使用 `-ReleaseNotesFile` 指定的 Markdown；省略时使用 `gh release create --generate-notes`。
- `-RunChecks` 会运行后端 pytest、前端 test gate、lint 和 build；发布脚本还会构建 Windows portable 包、导出公告、检查发布包法律文件并生成 SHA-256 校验文件。
- Windows portable 构建由 `.release-local/portable-win/build-portable.ps1` 负责；不要把 portable 运行态文件或用户数据写回仓库。
- `scripts/verify_release_legal_files.py` 同时校验 zip/tar 归档中的法律文件、路径安全和 portable runtime 许可文件。
- `docs/` 和 release notes 保持在 Git 外，不要 force-add。
- 下载的更新在下次启动时由 `python -m bot.updater apply-pending --repo-root <repo>` 应用。
- Updater 在应用前校验下载校验和、拒绝归档路径穿越，并在同步公告时把包内 `.web_announcements.json` 合并到运行态公告文件。

## 运行态路径

- 固定公网转发由公网服务器的 `frps` 和内网机器的内置 `frpc` 配合；配置 `TCB_NODE_ID`、`WEB_BASE_PATH`、`WEB_FIXED_PUBLIC_FORWARD_*`、`TCB_HUB_FRPS_*`，反向代理必须保留 `/node/<节点 ID>/` 前缀并支持 WebSocket。最小配置见 `README.md` 的“固定公网地址和反向代理”。
- 公告内容通过 `get_announcements_content_path()` 获取，默认位于 `~/.tcb/orbit-safe-claw/announcements/content.json`，可由 `TCB_DATA_DIR` 覆盖。
- 仓库根 `.web_announcements.json` 只用于旧数据迁移，不是当前维护位置。
- 不要把用户运行态数据写回仓库。

## 验证

- 启动脚本：`tests/test_start_scripts.py`。
- Runtime paths/startup：`tests/test_runtime_paths.py`、`tests/test_runtime_web_startup.py`。
- Updater/release packaging：`tests/test_updater_release_packaging.py`。
- Portable、归档法律文件、公告迁移和安全解压的变化优先补在 `tests/test_updater_release_packaging.py`，发布脚本行为仍需通过对应脚本的 `-RunChecks` 验证。
- 发布前运行后端测试、前端 test gate、build，并按脚本要求确认工作区状态。
