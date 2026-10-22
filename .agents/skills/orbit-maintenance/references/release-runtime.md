# 安装、运行态与发布

## 安装和启动

- Windows 安装：`install.bat`、`install.ps1`；启动：`start.bat`、`start.ps1`。
- Linux/macOS 安装：`install.sh`；启动：`start.sh`。
- 安装器检查 Python 3.10+、Node.js 18+ 和 Git；当前前端锁文件中 `pdfjs-dist@6.3.289` 要求 Node.js 22.13+，因此 Node 18 检查通过仍不足以满足锁定依赖。Windows 安装器可选下载固定 Codex `0.121.0`、cloudflared `2026.3.0`；Linux/macOS 安装器提示用户准备 Codex/Claude。示例插件默认跳过，可用安装器的 `InstallExamplePlugins` / `--install-example-plugins` 选项启用。
- `install.ps1` 使用检测到的 Python 安装依赖；`install.sh` 创建 `.venv`。源码启动脚本优先使用项目 `.venv`，否则查找系统 Python；启动步骤失败时最多安装依赖并重试一次，`TCB_STARTUP_FORCE_DEP_INSTALL` 可强制同步，创建 venv 时遵守 `TCB_STARTUP_USE_SYSTEM_PYTHON`。
- 源码启动顺序：迁移 `.env`、检查 updater、应用待更新包、按源码指纹检查前端构建、运行数据迁移、导入检查、进入宿主循环。前端指纹缓存位于仓库 `.tcb/startup`；`TCB_STARTUP_SKIP_DEP_SYNC` 跳过依赖同步及前端重建，`TCB_STARTUP_SKIP_FRONTEND_BUILD` 只跳过前端重建。
- `python -m bot` 经 `bot/__main__.py` 先完成存储迁移收尾和运行数据迁移，再调用 `bot/main.py:main()`；源码启动脚本预先迁移并传 `--tcb-migrations-checked`。`main()` 在 restart loop 中执行 `asyncio.run(run_all_bots())`，启动 Web 服务及按配置启用的 Telegram gateway。
- 重启请求设置 `config.RESTART_REQUESTED`、`config.RESTART_EVENT`；存在 `CLI_BRIDGE_SUPERVISOR=1` 时以退出码 `75` 交给启动器重启，否则 re-exec。源码启动器收到 `75` 只重跑宿主循环；待更新包应用位于循环外，需要重新运行启动脚本。启动/重启操作仍受根 `AGENTS.md` 约束。

## 发布

```powershell
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -ReleaseNotesFile .\docs\release-notes\v<version>.md
```

- 在线更新检查 GitHub Releases；另支持校验本地离线包并标记待应用，包类型与当前分发方式必须兼容。
- Release body 使用 `-ReleaseNotesFile` 指定的 Markdown；省略时使用 `gh release create --generate-notes`。
- 默认 `-Mode BuildAndPublish` 会构建、提交发布改动、推送分支/tag 并创建 GitHub Release；`BuildOnly` 只构建，`PublishOnly` 复用已有产物。`-RunChecks` 是构建阶段选项，执行 `python -m pytest tests examples/plugins -q`、前端 test gate 和 lint；构建流程另外生成前端、Windows portable 包、公告快照、法律文件和 SHA-256 校验文件。
- Windows portable 由 `.release-local/portable-win/build-portable.ps1` 构建，固定 Node `22.17.1`、`@earendil-works/pi-coding-agent@0.74.2`、`pi-workspace-history@0.2.2`，并包含 Python、Git 和 Python 依赖；包内启动器使用自己的 bootstrap。
- `scripts/verify_release_legal_files.py` 同时校验 zip/tar 归档中的法律文件、路径安全和 portable runtime 许可文件。
- `docs/` 和 release notes 保持在 Git 外，不要 force-add。
- 源码启动脚本通过 `python -m bot.updater apply-pending --repo-root <repo>` 应用待更新包。当前 portable 生成的启动器未调用 `apply-pending`，直接 `python -m bot` 也不应用待更新包；不要据此承诺这两种入口重启即可完成更新。
- 在线包下载校验 SHA-256 sidecar，离线准备记录文件哈希；应用时复核已记录哈希，检查归档路径、分发类型与受保护路径，写入失败可恢复备份。需要时重建前端，并把包内 `.web_announcements.json` 合并到运行态公告文件。

## 运行态路径

- 固定公网转发由公网服务器的 `frps` 和内网机器的内置 `frpc` 配合；配置 `TCB_NODE_ID`、`WEB_BASE_PATH`、`WEB_FIXED_PUBLIC_FORWARD_*`、`TCB_HUB_FRPS_*`、`TCB_HUB_NODE_TOKEN`、`TCB_HUB_FRPC_*`，反向代理必须保留 `/node/<节点 ID>/` 前缀并支持 WebSocket。最小配置见 `README.md` 的“固定公网地址和反向代理”。
- `bot/runtime_paths.py` 区分 storage root 与 app data root。未迁移时分别为 `~/.tcb` 和 `~/.tcb/orbit-safe-claw`；`TCB_DATA_DIR`（环境变量或 `.env`）只覆盖 app data root。
- 已提交的 `~/.tcb/storage.json` 定位器优先确定两类根目录；目标缺失时报错，冲突的 `TCB_DATA_DIR` 被拒绝，当前进程冻结路径直到重启。迁移流程见 `bot/storage_migration.py`、`storage_runtime.py`；插件、历史和附件等调用者应使用路径函数。
- Portable 设置 `TCB_DATA_DIR=<包>/data/orbit-safe-claw`、Pi home 为 `<包>/data/pi-home`；插件和聊天历史等 storage-root 数据仍遵循 `get_tcb_home_root()`。已有定位器与 portable 覆盖冲突时也会报错。
- 公告内容通过 `get_announcements_content_path()` 获取；仓库根 `.web_announcements.json` 用于旧数据迁移和发布包公告快照。用户内容应写当前运行态目录；现有仓库局部运行文件（如 `.tcb/startup`、`.plugins`、`managed_bots.json`）按各自实现维护并保持在 Git 外。

## 验证

- 启动脚本：`tests/test_start_scripts.py`。
- Runtime paths、迁移和启动：`tests/test_runtime_paths.py`、`tests/test_storage_migration.py`、`tests/test_storage_runtime.py`、`tests/test_runtime_data_migrations.py`、`tests/test_main_migration_gate.py`、`tests/test_runtime_web_startup.py`，按改动选择。
- Updater/release packaging：`tests/test_updater_release_packaging.py`。
- Portable、归档法律文件、公告迁移和安全解压的行为变化优先复用 `tests/test_updater_release_packaging.py`。文档核对不执行发布脚本；实际发布时按脚本运行检查并确认工作区与发布参数。
