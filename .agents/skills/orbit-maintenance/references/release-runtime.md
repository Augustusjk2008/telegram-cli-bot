# 安装、运行态与发布

## 安装和启动

- Windows 安装：`install.bat`、`install.ps1`；启动：`start.bat`、`start.ps1`。
- Linux/macOS 安装：`install.sh`；启动：`start.sh`。
- 安装器检查 Python 3.10+、Node.js 22.13+ 和 Git；Node 检查与下载回退须满足前端锁文件要求。Windows 安装器可选下载固定 Codex `0.121.0`、cloudflared `2026.3.0`；Linux/macOS 安装器提示用户准备 Codex/Claude。示例插件默认跳过，可用安装器的 `InstallExamplePlugins` / `--install-example-plugins` 选项启用。
- `install.ps1` 使用检测到的 Python 安装依赖；`install.sh` 创建 `.venv`。源码启动脚本优先使用项目 `.venv`，否则查找系统 Python；启动步骤失败时最多安装依赖并重试一次，`TCB_STARTUP_FORCE_DEP_INSTALL` 可强制同步，创建 venv 时遵守 `TCB_STARTUP_USE_SYSTEM_PYTHON`。
- `start.bat` 把启动命令及其后的退出处理放在同一个预解析代码块中：升级可能在运行期间替换该文件，cmd.exe 会按旧偏移重读。`start.ps1` 与 `scripts/service-status.ps1` 用 `-Encoding UTF8` 读取 Python 写出的 JSON（Windows PowerShell 5.1 默认按 ANSI 代码页解码）。
- 源码启动器先创建安装目录外的执行器快照；有中断事务时先恢复。正常启动完成 `.env`、迁移与导入检查后，将宿主交给独立 supervisor。启动时直接使用已有的 `front/dist`，不会自动重建前端；修改前端后由用户手动运行 `npm run build`。
- `python -m bot` 经 `bot/__main__.py` 先完成存储迁移收尾和运行数据迁移，再调用 `bot/main.py:main()`；源码启动脚本预先迁移并传 `--tcb-migrations-checked`。`main()` 在 restart loop 中执行 `asyncio.run(run_all_bots())`，启动 Web 服务及按配置启用的 Telegram gateway。
- 普通重启设置 `RESTART_REQUESTED` / `RESTART_EVENT`，官方 supervisor 处理退出码 `75`；更新使用独立请求及退出码 `76`，且只消费 `waiting_restart` 任务。`CLI_BRIDGE_UPDATE_PROTOCOL=1` 表示官方启动器能力；直接 `python -m bot` 仅检查和准备。当前宿主的操作仍受根 `AGENTS.md` 约束。

## 升级事务

- `bot/update_state.py` 通过运行态路径定位安装专属状态，使用规范化根目录身份、修订号、原子写入和 OS 文件锁。`bot/update_service.py` 统一自动/手动/离线/上传准备；SSE 只订阅任务，断线不会重复下载。自动检查在 Web 宿主启动时及每 6 小时（`UPDATE_AUTO_CHECK_INTERVAL_SECONDS`）运行，只准备不应用，不会重新准备当前任务已取消、或下载完成后才失败的同一版本（只自动重试下载中断）；在线准备拒绝与运行版本相同的 Release（`update_not_available`）。状态每次读取都重新计算 `update_available`，并给出任务目录中已存在的 `preparation_log` / `runner_log`。上传可带 `?size=`：超限提前拒绝并提供进度百分比，上传期间的状态写入节流且在线程中执行。`state.json` 以纯 ASCII JSON 写入。旧状态只认领可证明属于当前安装的包，并要求重新准备。
- 宿主与启动器的安装锁位于独立控制目录，数据目录迁移不会改变锁身份；直接 `python -m bot` 也参与互斥。新宿主通过带进程身份的交接文件报告当前状态路径，启动器在普通重启和升级退出后重新读取，避免消费迁移前的状态。健康确认前暂停新任务，成功或安全恢复后开放，被接受的宿主随即移除 `TCB_UPDATE_JOB_ID` 与 `TCB_UPDATE_HEALTH_TOKEN`。
- 阶段为 `preparing → ready → waiting_restart → applying → awaiting_health → succeeded`；准备可取消/重试：取消只核对任务 ID 与阶段（准备进度每秒多次推进修订号），并终止正在运行的 pip/npm 进程树；新任务遇到同一 Release 的已失败、已取消或就绪前任务时接管其下载断点或已校验的完整包。应用失败进入 `rolling_back → rolled_back / recovery_required`。应用绑定任务 ID 与修订号，并阻止运行中的 Agent、集群任务和存储迁移；Web 宿主先在线程中核验全部原文件与暂存文件哈希，再在事件循环内关闭准入并做空闲检查。
- `scripts/update_transaction.py` 跳过内容与可执行位都已与暂存文件一致的目标（不备份、不改写，日志记 `unchanged_skipped`），其余目标在替换前复制并验证全部备份，落盘记录操作意图；Windows 瞬时占用（winerror 5/32/33）的替换与删除会短暂重试；恢复复制备份且可重复执行。中断时保留事务目录；旧 `.update-apply-*` 材料不全时报告人工恢复要求。
- `scripts/update_package.py` 统一清单、版本、归档路径、平台架构、包类型及文件哈希验证。保护配置和实际存储路径；源码本地修改、未知文件所有权及修改过的托管扩展作为冲突保留。废弃文件必须有旧清单证明归属。
- `bot/update_preparation.py` 在稳定的独立路径准备 Python 环境并核验依赖指纹。前端包记录部署参数与资源哈希，匹配时复用；重建使用暂存目录与 `npm ci`。跳过同步选项不会授权不满足要求的更新。
- `scripts/update_runner.py` 与标准库辅助模块复制到固定快照运行；绿色版控制 Python 位于更新目标外。旧宿主退出并释放安装锁后才应用。新实例健康检查核验任务、令牌、版本、实例和实际监听地址，默认等待 180 秒，`TCB_UPDATE_HEALTH_TIMEOUT_SECONDS`（30–1800）在确认应用时写入任务；恢复前以 `host.lock` 判断宿主是否仍在运行，记录的 PID 只用于不持锁的 legacy 宿主；前端资源完整且必要迁移结束才就绪。外部模型、Telegram 和隧道状态不单独触发恢复。
- 旧程序及依赖环境保留到健康确认。恢复后再次验证旧版本，结果中提供可重试恢复命令。公告同步是独立后续动作，其失败不能改变程序升级成功状态。数据迁移兼容性由 `bot/update_migration_gate.py` 检查，程序回滚保持用户数据。
- 首次旧版升级使用完整新包中的 `scripts/update_bootstrap.py`，参数与操作顺序见两个根 README；没有 Git 或旧清单时需原版本完整包及其 SHA-256 建立基线。工具先准备，由用户退出旧服务后显式应用，保留引导目录与恢复命令。


## 发布

```powershell
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -ReleaseNotesFile .\docs\release-notes\v<version>.md
```

- 在线准备绑定具体 GitHub Release 与资产；离线包由宿主路径或管理员流式上传提供。版本、分发标记与清单必须一致，默认拒绝降级及不兼容平台/包类型。
- Release body 使用 `-ReleaseNotesFile` 指定的 Markdown；省略时使用 `gh release create --generate-notes`。
- 默认 `-Mode BuildAndPublish` 会构建、提交发布改动、推送分支/tag 并创建 GitHub Release；`BuildOnly` 只构建，`PublishOnly` 复用已有产物。`-RunChecks` 是构建阶段选项，执行 `python -m pytest tests examples/plugins -q`、前端 test gate 和 lint；构建流程另外生成前端、Windows portable 包、公告快照、法律文件和 SHA-256 校验文件。
- Windows portable 由 `.release-local/portable-win/build-portable.ps1` 构建，固定 Node `22.17.1`、`@earendil-works/pi-coding-agent@0.74.2`、`pi-workspace-history@0.2.2`，并包含 Python、Git 和 Python 依赖；包内启动器使用自己的 bootstrap。
- `scripts/verify_release_legal_files.py` 只检查 zip/tar 中必需的法律文件与 portable runtime 许可文件是否存在。`scripts/update_package.py verify` 独立检查更新协议、文件清单/哈希、版本及提交身份。PowerShell/Shell 发布入口均运行两类校验；`PublishOnly` 必须匹配当前提交且禁止 dirty 产物。
- `docs/` 和 release notes 保持在 Git 外，不要 force-add。
- 绿色版只在首次启动缺失时生成 Pi `settings.json` / `models.json`；仅 `data/pi-home/.pi/agent/extensions/tcb-cluster.ts` 与 `workspace-history.ts` 登记为数据目录下的托管文件。发布清单包含实际源码提交、dirty 标志、依赖指纹、前端构建参数及全部程序文件哈希。


## 运行态路径

- 固定公网转发由公网服务器的 `frps` 和内网机器的内置 `frpc` 配合；配置 `TCB_NODE_ID`、`WEB_BASE_PATH`、`WEB_FIXED_PUBLIC_FORWARD_*`、`TCB_HUB_FRPS_*`、`TCB_HUB_NODE_TOKEN`、`TCB_HUB_FRPC_*`，反向代理必须保留 `/node/<节点 ID>/` 前缀并支持 WebSocket。最小配置见 `README.md` 的“固定公网地址和反向代理”。
- `bot/runtime_paths.py` 区分 storage root 与 app data root。未迁移时分别为 `~/.tcb` 和 `~/.tcb/orbit-safe-claw`；`TCB_DATA_DIR`（环境变量或 `.env`）只覆盖 app data root。
- 已提交的 `~/.tcb/storage.json` 定位器优先确定两类根目录；目标缺失时报错，冲突的 `TCB_DATA_DIR` 被拒绝，当前进程冻结路径直到重启。迁移流程见 `bot/storage_migration.py`、`storage_runtime.py`；插件、历史和附件等调用者应使用路径函数。
- 存储迁移移动 `updates/<安装>/state.json`，但 `updates/<安装>/jobs`（包、暂存、冻结执行器、事务备份、依赖环境）是安装程序材料：不复制、不改写其绝对路径、清理时保留在原位置，使状态中的 `python_executable` 与恢复材料保持有效。
- `UpdateStore.prune_job_dirs()` 只清理当前状态根 `jobs/` 下的有效任务 ID 子目录：在持有 `preparation.lock` 时运行（`_reserve` 新建任务后；执行器在 `succeeded`/`rolled_back` 后非阻塞获取）。当前任务、被状态任意绝对路径值、`sys.executable`（`abspath`，不解析符号链接）或执行器快照（`CLI_BRIDGE_UPDATE_RUNNER_PATH`）引用的任务、24 小时内修改的目录、事务日志未以 `committed`/`rolled_back` 结束的目录以及链接一律保留；当前任务处于交接、应用、恢复或未知阶段、状态不可读、受监管宿主缺少执行器路径时不清理。删除失败只记录日志。`launcher-info` 在 supervisor 与 host 锁均空闲时，清理控制目录中超过 24 小时且未被状态、启动器指针或当前进程引用的 `launcher-*` 与控制 Python 快照。
- Portable 设置 `TCB_PORTABLE_ROOT=<包>`，将 `<包>/.tcb` 作为独立 storage root，避免读取宿主用户的迁移定位器；默认 app data 为 `<包>/data/orbit-safe-claw`、Pi home 为 `<包>/data/pi-home`。绿色版迁移后由包内定位器决定 app data root，并清除默认 `TCB_DATA_DIR` 覆盖。
- 公告内容通过 `get_announcements_content_path()` 获取；仓库根 `.web_announcements.json` 用于旧数据迁移和发布包公告快照。用户内容应写当前运行态目录；现有仓库局部运行文件（如 `.tcb/startup`、`.plugins`、`managed_bots.json`）按各自实现维护并保持在 Git 外。

## 验证

- 启动脚本与执行器：`tests/test_start_scripts.py`、`tests/test_update_runner.py`、`tests/test_update_preparation.py`。使用模拟宿主，不监听端口。
- Runtime paths、迁移和启动：`tests/test_runtime_paths.py`、`tests/test_storage_migration.py`、`tests/test_storage_runtime.py`、`tests/test_runtime_data_migrations.py`、`tests/test_main_migration_gate.py`、`tests/test_runtime_web_startup.py`，按改动选择。
- Updater/release packaging：`tests/test_updater_release_packaging.py`；事务断点：`tests/test_update_transaction.py`；任务隔离/API：`tests/test_update_service.py`。真实平台升级演练由用户在独立测试副本操作；交付区分模拟结果与真实平台验证。
- Portable、归档法律文件、公告迁移和安全解压的行为变化优先复用 `tests/test_updater_release_packaging.py`。文档核对不执行发布脚本；实际发布时按脚本运行检查并确认工作区与发布参数。
