# Orbit Safe Claw

远程控制 AI 智能体的多 Bot Web 控制台。它把 `codex` / `claude` / `kimi`、项目文件、Git、终端、插件视图、Assistant 自动化和管理中心聚合到同一浏览器界面，用于统一调度多个仓库、子 agent、集群任务和后台维护流程。

## 核心能力

- 多 Bot 编排：主 Bot + 托管 Bot 共同运行，每个 Bot 绑定 CLI、工作目录、运行模式、CLI 参数和独立会话。
- 集群协作：CLI Bot 支持子 agents、`@agent_id` 路由、集群模板、JSON bundle、MCP 连接和模型档位，适合并行分派审查、实现、验证等任务。
- Assistant Ops：提供 proposal 审批、patch 生成 / dry-run / apply、memory、diagnostics、audit、Automation 队列、cron 和 runs，承载长期维护流程。
- 项目工作台：Chat、Files、Git、Terminal、Debug 组成一体化开发界面，覆盖对话执行、文件编辑、版本控制、终端和系统脚本。
- 插件运行时：基于 `plugin.json` 扩展文件视图、插件配置和进程运行能力，支持 session 型重型视图，内置 Vivado waveform 示例。
- 管理与交付：Admin Center 覆盖用户权限、邀请码、公告发布、更新检查、Release 下载和离线包管理；Cloudflare quick tunnel 支持移动端远程访问。

## 环境要求

- Windows 10 / 11
- Ubuntu / Debian Linux
- macOS 12+（首版为源码包，非 `.app` / DMG）
- Python 3.10+
- Node.js 18+
- Git

## 下载与安装

推荐用 GitHub Releases 正式包：

Windows：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 绿色版：下载 `orbit-safe-claw-windows-x64-<version>.zip`，解压后运行 `start.bat`
3. 安装版：下载 `orbit-safe-claw-windows-x64-installer-<version>.zip`，解压后运行 `install.bat`

Windows 绿色版已带 Python、Git 和前端构建产物，无需安装 Python / Node / Git；不内置 AI CLI。使用前需本机可运行 `codex --version` / `claude --version` / `kimi info`，并可在 Web 设置页或 `.env` 修改 `CLI_TYPE` / `CLI_PATH`。

Linux：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新 `orbit-safe-claw-linux-x64-<version>.tar.gz`
3. 解压后运行 `bash install.sh`

macOS：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新 `orbit-safe-claw-macos-universal-<version>.tar.gz`
3. 解压后运行：

```bash
tar -xzf orbit-safe-claw-macos-universal-<version>.tar.gz
cd orbit-safe-claw
bash install.sh
bash start.sh
```

macOS 需要 Python 3.10+、Node.js 18+、Git，推荐先装 Homebrew。AI CLI 不内置，需自行安装 `codex` / `claude` / `kimi`。

源码快照安装：

Windows：

```powershell
$zip="$env:TEMP\\orbit-safe-claw.zip"; Invoke-WebRequest "https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.zip" -OutFile $zip; Expand-Archive $zip -DestinationPath . -Force; Set-Location .\telegram-cli-bot-master; .\install.bat
```

Linux：

```bash
curl -L https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.tar.gz | tar -xz && cd telegram-cli-bot-master && bash install.sh
```

macOS：

```bash
curl -L https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.tar.gz | tar -xz && cd telegram-cli-bot-master && bash install.sh
```

安装器会准备：

- Python / Node.js / Git 检查
- 后端依赖
- 前端依赖和构建
- `.env`

安装器会检查本机 `codex` / `claude` / `kimi` 可用性，并给出后续配置提示。

## 如何运行

Windows：

- 双击 `start.bat`
- 或终端运行 `.\start.bat`

Linux：

- 运行 `bash start.sh`

macOS：

- 运行 `bash start.sh`

首次启动时，Windows 的 `start.bat` / `start.ps1` 会自动补齐 `.env` 配置，再继续启动。

默认 Web 绑定地址 `0.0.0.0:8765`，本机访问可用 `http://127.0.0.1:8765`。登录口令使用 `.env` 里的 `WEB_API_TOKEN`。

如果 `.env` 里的 `WEB_PORT` 已被占用，启动时会自动尝试 `+1`，直到找到可用端口；控制台、健康检查和 tunnel 都会跟随实际端口。

如果启用了 `WEB_TUNNEL_MODE=cloudflare_quick` 且 tunnel 拉起成功，控制台会打印公网地址二维码，方便手机扫码打开。

## 基本配置

首次安装后至少确认这些 `.env` 项：

```env
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=C:\Users\YourName\project
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=change-this-password
```

如需托管更多 Bot，可参考仓库内 `managed_bots.example.json` 新建本地 `managed_bots.json`：

```json
{
  "bots": [
    {
      "alias": "repo2",
      "cli_type": "codex",
      "cli_path": "codex",
      "working_dir": "C:/work/repo2",
      "enabled": true,
      "bot_mode": "cli"
    },
    {
      "alias": "assistant1",
      "cli_type": "codex",
      "cli_path": "codex",
      "working_dir": "C:/work/assistant-home",
      "enabled": true,
      "bot_mode": "assistant"
    }
  ]
}
```

运行模型：

- `cli` Bot 支持子 agent 和集群配置
- `assistant` Bot 走宿主管理流程，工作目录下会维护 `.assistant/`
- `assistant` Bot 采用单实例宿主模型

## 工作界面

- `cli` Bot：把 Web 消息转发到本地 `codex` / `claude` / `kimi`，保留会话、trace、CLI 参数和子 agent 作用域。
- `assistant` Bot：走宿主管理流程，在工作目录下维护 `.assistant/`，用于长期记忆、任务编排和自动化维护。
- Desktop Workbench：面向重复开发操作，集中承载文件树、编辑器、Git、终端、聊天和插件视图。
- Admin Center：面向运维管理，集中承载账号权限、邀请、公告和更新。

## 更新

主 Bot 设置页和管理中心支持 GitHub Release 自动检查、下载更新和离线包查看。下载后的更新会在下次启动或重启后生效。

更新包按平台匹配：Windows 安装版 / 绿色版、Linux、macOS。macOS 离线包名形如 `orbit-safe-claw-macos-universal-<version>.tar.gz`。

首次安装生成的 `.env` 默认写入：

```env
APP_UPDATE_REPOSITORY=Augustusjk2008/telegram-cli-bot
```

如果你用自己的 GitHub Releases 仓库，改成对应 `owner/repo` 即可。

## 开发命令

```bash
python -m bot
python -m pytest tests -q
cd front && npm test
cd front && npm run build
```

常用聚焦测试：

```bash
python -m pytest tests/test_web_api.py -q
python -m pytest tests/test_assistant.py -q
cd front && npm test -- --run src/test/chat-screen.test.tsx src/test/desktop-bot-manager-screen.test.tsx
```
