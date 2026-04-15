# Release Foundation Design

## Summary

本设计只覆盖 1.0 开源发布前的基础层，不包含品牌命名和启动页视觉包装。

阶段一范围固定为：

- Linux 安装脚本与启动脚本
- GitHub Release 驱动的自动更新设计
- 开源发布前的仓库整理与发布包边界
- `AGENTS.md` / `CLAUDE.md` 同步

明确不在本阶段处理：

- 项目最终名字
- 启动页 / 登录页视觉改版
- 更重型的 updater 回滚、签名、多通道体系

## Goals

- 让 Windows 与 Ubuntu / Debian 都有清晰一致的安装和启动体验
- 为 1.0 开源发布建立稳定的版本检查与更新机制
- 把不应该公开的本地状态、配置、缓存从源码仓库与 release 包中分离出去
- 让 `AGENTS.md` 与 `CLAUDE.md` 反映发布后的真实项目形态

## Non-Goals

- 不支持 `git pull` 作为用户更新主通道
- 不支持运行中进程自覆盖更新
- 不扩展 Linux 发行版支持范围到 Ubuntu / Debian 之外
- 不为 Linux 增加 systemd、桌面快捷方式或 GUI 安装器

## Constraints

- 当前保留的本地 CLI 只有 `codex` 与 `claude`
- 自动更新只检查 GitHub Releases，且更新包下载后必须等待用户重启生效
- 主 bot 设置页需要能控制是否自动检查更新
- Linux 安装器对系统包安装只面向 `apt`
- `codex` / `claude` 只做检查，不自动安装

## Phase Boundary

阶段一只做发布基础，不做产品包装。

阶段一完成后，应具备：

- Windows / Linux 都能安装并启动
- 主 bot 设置页能看到更新状态并控制自动检查
- 启动脚本能在真正运行前应用已下载的更新包
- 仓库能以开源形态安全发布

阶段二另行处理：

- 项目命名
- 启动页 / 登录页 / 首屏品牌表达

## Linux Installation Design

新增根目录 `install.sh`，定位为 Ubuntu / Debian 的安装入口，行为与 Windows `install.bat + install.ps1` 保持同一心智模型。

### Supported Targets

- Ubuntu
- Debian

### Entry Mode

- 支持 `bash install.sh`
- 支持 `chmod +x install.sh && ./install.sh`
- 输出简短中文步骤提示

### Installation Flow

1. 检查仓库必要文件：
   - `requirements.txt`
   - `front/package.json`
   - `.env.example`
2. 检查操作系统和包管理器：
   - `/etc/os-release`
   - `apt`
   - `sudo`
3. 检查并安装基础系统依赖：
   - `python3`
   - `python3-pip`
   - `python3-venv`
   - `git`
   - `curl`
   - `ca-certificates`
4. 检查 Node.js：
   - 版本 `>=18` 则直接复用
   - 否则通过 NodeSource LTS 安装
5. 检查 `codex` / `claude`：
   - 仅检查
   - 若两者都不存在，输出明显警告与简短安装说明
6. 安装后端依赖：
   - `python3 -m pip install --upgrade pip`
   - `python3 -m pip install -r requirements.txt`
7. 安装前端依赖与构建：
   - `npm install`
   - `npm run build`
8. 生成或保留 `.env`

### CLI Warning Behavior

如果未检测到 `codex` 与 `claude`：

- 不阻断其余安装步骤
- 明确提示用户先完成 CLI 安装和登录
- 明确提示用户之后确认：
  - `codex --version`
  - `claude --version`
- 提示可重新运行安装器或手动修改 `.env`

### `.env` Strategy

和 Windows 安装器保持一致：

- 若已有 `.env`，默认保留，可交互选择重建
- 若新建 `.env`，基于 `.env.example`
- 自动填充：
  - `CLI_TYPE`
  - `CLI_PATH`
  - `WORKING_DIR`
  - `WEB_ENABLED=true`
  - `WEB_HOST=127.0.0.1`
  - `WEB_PORT=8765`
  - `WEB_API_TOKEN`

### Verification Modes

Linux 安装器保留两种非正式运行模式，方便后续验证：

- `--check-only`
- `--non-interactive`

这些模式用于检查和默认填充，不执行完整交互安装。

## Linux Startup Design

更新现有 `start.sh`，使其与新版 Windows 启动脚本对齐。

### Runtime Behavior

- 当前控制台直接运行
- 不做后台化
- 保留 `75` 退出码重启机制
- 缺失 `.env` 时直接报错退出

### Startup Steps

1. 进入仓库根目录
2. 读取 `.env`
3. 检查是否存在待应用更新
4. 若有已下载的更新包，则先应用更新
5. 检查公网访问配置：
   - `WEB_PUBLIC_URL`
   - `WEB_TUNNEL_MODE`
6. 若未配置公网访问，则输出提示：
   - 可设置 `WEB_TUNNEL_MODE=cloudflare_quick`
   - 或配置反向代理后填写 `WEB_PUBLIC_URL`
7. 设置运行环境：
   - `CLI_BRIDGE_SUPERVISOR=1`
   - `WEB_ENABLED=true`
8. 选择 Python：
   - 优先 `python3`
   - 回退 `python`
9. 执行 `python -m bot`

### Non-Goals For Linux Startup

- 不新增 systemd unit
- 不新增 desktop entry
- 不做 Linux 下的管理员提权包装

## Auto Update Design

自动更新采用 GitHub Release 包机制，不走 `git pull`，不在运行中进程里直接替换自身文件。

### Update Source

- 当前版本：例如 `1.0.0`
- GitHub Release tag：`v1.0.0`
- 更新检查只面向正式 release

### High-Level Model

自动更新分为两个阶段：

1. Web 运行时：
   - 检查 release
   - 下载更新包
   - 记录待应用状态
2. 下次启动时：
   - 启动脚本发现待更新
   - 解压并覆盖程序文件
   - 保留用户本地状态
   - 再启动新版本

### Why Not Live Self-Replacement

不在运行中的进程里直接替换文件，原因是：

- Windows 文件占用风险高
- 跨 Windows / Linux 逻辑容易分裂
- 回滚和失败处理复杂度显著上升

对 1.0 而言，“下载完成，重启生效”是更稳的边界。

## Update Service Responsibilities

新增独立 updater 模块，后端职责限定为：

- 提供当前应用版本
- 查询 GitHub Releases 最新版本
- 比较当前版本与最新版本
- 下载匹配平台的发布包到本地更新缓存目录
- 记录待应用更新状态

不负责：

- 运行中直接覆盖文件
- 自动重启
- 自动回滚

## Update State Persistence

更新状态持久化到 `.web_admin_settings.json`，原因是它属于主 bot 的全局管理设置，而不是某个聊天会话或单个 bot 的业务数据。

建议新增字段：

- `update_enabled`
- `update_channel`
- `last_checked_at`
- `last_available_version`
- `last_available_release_url`
- `pending_update_version`
- `pending_update_path`
- `pending_update_notes`
- `pending_update_platform`

### Settings Semantics

- `update_enabled`
  - 控制是否自动定时检查更新
- `update_channel`
  - 1.0 固定为 `release`
- `last_checked_at`
  - 最近一次检查时间
- `last_available_version`
  - 最近发现的可用版本
- `pending_update_*`
  - 下载完成但尚未在启动时应用的更新信息

## Main Bot Settings Integration

主 bot 设置页新增“版本更新”区块，只在 `botAlias === "main"` 下显示。

### UI Content

- 当前版本
- 最新版本
- 上次检查时间
- 自动检查更新开关
- “立即检查”按钮
- “下载更新”按钮
- “已下载，重启后完成更新”提示

### UI Behavior

- 自动检查关闭时，仍允许手动检查
- 有新版本但未下载时，展示下载入口
- 已下载未应用时，突出显示“重启后完成更新”
- 下载失败时展示明确错误

### Frontend Files

- `front/src/screens/SettingsScreen.tsx`
- `front/src/services/types.ts`
- `front/src/services/webBotClient.ts`
- `front/src/services/realWebBotClient.ts`

### Backend Files

- 新增 updater 模块
- `bot/app_settings.py`
- `bot/web/server.py`

## Update Application On Startup

Windows 与 Linux 启动脚本都要在真正运行服务前检查待应用更新。

### Startup Apply Flow

1. 读取更新状态
2. 判断是否存在已下载更新包
3. 解压到临时目录
4. 覆盖程序文件
5. 跳过本地持久化文件
6. 清除待应用更新标记
7. 启动新版本

### Files That Must Never Be Overwritten

- `.env`
- `managed_bots.json`
- `.session_store.json`
- `.web_admin_settings.json`
- `.assistant/`
- `.claude/`
- 缓存与临时目录

## Repository Hygiene Before Open Source

源码仓库与 release 包必须区分。

### Should Be In Git

- 源码：
  - `bot/`
  - `front/src/`
  - `tests/`
  - `scripts/`
- 启动与安装入口：
  - `start.bat`
  - `start.ps1`
  - `start.sh`
  - `install.bat`
  - `install.ps1`
  - `install.sh`
- 配置样例与文档：
  - `.env.example`
  - `managed_bots.example.json`
  - `README.md`
  - `AGENTS.md`
  - `CLAUDE.md`
  - 其他部署/发布文档
- 依赖与元信息：
  - `requirements.txt`
  - `front/package.json`
  - `front/package-lock.json`
  - `pytest.ini`
  - `.gitignore`
  - `.gitattributes`

### Must Not Be In Git

- `.env`
- `managed_bots.json`
- `.session_store.json`
- `.web_admin_settings.json`
- `.web_tunnel_state.json`
- `.cloudflared_url`
- `.venv/`
- `venv/`
- `__pycache__/`
- `.pytest_cache/`
- `.assistant/` 的真实运行态内容
- `.claude/` 的本地状态
- `.worktrees/`
- `tmp_bot_create_check/`
- `.whisper_temp/`

## Release Package Contents

release 包面向最终用户运行，不等于源码仓库。

### Should Be Included

- 后端运行源码
- 前端构建产物 `front/dist`
- 安装脚本
- 启动脚本
- `.env.example`
- `managed_bots.example.json`
- `README.md`

### Should Not Be Included

- `.git/`
- 测试目录
- 本地缓存
- 本地状态文件
- 用户私有配置
- 任何 token / session / 本机路径数据

## Existing Remote Repository Remediation

当前远端仓库比本地落后，但历史里已经出现过不适合公开的文件。由于泄露密钥已经停用，因此优先建议修复现有仓库，而不是删除后重建。

### Strategy

- 不删除 GitHub 仓库
- 清洗敏感文件历史
- 强推覆盖远端历史
- 使用 example 文件替代真实本地配置

### Sensitive History Targets

需要从历史中清理的典型文件包括：

- `.env`
- `managed_bots.json`
- `.web_tunnel_state.json`
- `.cloudflared_url`

### Release Preparation Sequence

1. 清洗历史中的敏感文件
2. 确认 `.gitignore` 覆盖完整
3. 生成 `managed_bots.example.json`
4. 核对 README 与实际安装/启动行为一致
5. 打包 release 附件
6. 发布 `v1.0.0`

## AGENTS And CLAUDE Synchronization

`AGENTS.md` 与 `CLAUDE.md` 继续保持内容一致。

需要同步的关键信息：

- 项目定位为 Web-only
- 当前 CLI 仅支持 `codex` / `claude`
- Windows 安装入口：`install.bat`
- Linux 安装入口：`install.sh`
- Windows 启动入口：`start.bat`
- Linux 启动入口：`start.sh`
- 自动更新机制：
  - GitHub Release 检查
  - 下载后重启生效
  - main bot 设置页可控制
- 发布约束：
  - 不提交真实本地状态
  - 不提交真实 bot 配置
  - 使用 example 配置文件

## Required Files And Modules

阶段一实施时，预计涉及：

- `install.sh`
- `start.sh`
- Windows 启动脚本与安装脚本的更新应用逻辑
- updater 模块
- `bot/app_settings.py`
- `bot/web/server.py`
- `front/src/screens/SettingsScreen.tsx`
- `front/src/services/types.ts`
- `front/src/services/webBotClient.ts`
- `front/src/services/realWebBotClient.ts`
- `.gitignore`
- `managed_bots.example.json`
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`

## Data Flow Summary

### Update Check Flow

1. Web 服务启动
2. 读取 `.web_admin_settings.json`
3. 若开启自动检查更新，则查询 GitHub Releases
4. 写入最新版本状态
5. 主 bot 设置页读取并展示更新状态

### Update Download Flow

1. 用户在主 bot 设置页点击下载更新
2. 后端下载对应平台 release 包
3. 将包写入本地更新缓存目录
4. 更新 `.web_admin_settings.json` 的待应用状态
5. 前端展示“重启后完成更新”

### Update Apply Flow

1. 用户通过启动脚本重新启动应用
2. 启动脚本先检查待应用更新
3. 若存在待更新，则完成解压与覆盖
4. 保留本地配置与状态文件
5. 清理待更新标记
6. 启动新版本

## Risks

### Risk 1: Release Package And Source Divergence

如果 release 包中的 `front/dist` 与源码版本不同步，用户会遇到前后端不匹配问题。

缓解方式：

- release 打包前强制重建前端
- 把版本信息写入统一来源

### Risk 2: Update Package Overwrites Local State

如果覆盖逻辑没排除本地状态文件，会损坏用户配置。

缓解方式：

- 明确排除清单
- 仅覆盖程序文件

### Risk 3: Repository History Still Contains Sensitive Files

仅靠 `.gitignore` 不足以修复历史泄露。

缓解方式：

- 清洗 git 历史
- 再强推远端

### Risk 4: Linux Dependency Installation Drift

Ubuntu / Debian 版本差异可能导致 Node 安装命令漂移。

缓解方式：

- 1.0 只保证 Ubuntu / Debian
- 安装器输出明确失败提示与步骤位置

## Testing Guidance

阶段一实施后至少需要验证：

- Windows 安装器 / 启动脚本
- Linux 安装器 / 启动脚本
- 主 bot 设置页更新开关与状态展示
- updater 服务的检查 / 下载 / 待应用状态流转
- 启动脚本应用更新时不会覆盖本地状态文件
- `AGENTS.md` / `CLAUDE.md` 同步一致

## Deferred To Phase Two

以下内容明确延后：

- 项目命名
- 启动页 / 登录页视觉方向
- 1.0 品牌包装与首屏设计
