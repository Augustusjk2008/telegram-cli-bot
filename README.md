# Orbit Safe Claw 🦞

把本地 `codex` / `claude` CLI 封装成网页控制台。支持桌面和手机浏览器，当前仅保留 Web 入口，不再包含 Telegram 机器人入口。

## 现在支持什么

- 本地 CLI：`codex`、`claude`
- Bot 模式：`cli`、`assistant`
- 1 个主 Bot + 多个托管 Bot（`managed_bots.json`），全局最多 1 个 `assistant` Bot
- CLI Bot 子 agent：非集群模式下拉切换 active agent；集群模式消息里用 `@agent_id`
- assistant 宿主管理能力：proposal、patch 生成 / apply、memory、diagnostics、audit、Automation 队列 / cron / runs
- Web 面板：Chat、Files、Git、Terminal、Debug、Plugins、Settings、Assistant Ops
- 可选 Cloudflare quick tunnel，方便手机直接访问

## 环境要求

- Windows 10 / 11
- Ubuntu / Debian Linux
- Python 3.10+
- Node.js 18+
- Git

## 下载与安装

推荐用 GitHub Releases 正式包：

Windows：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新 `orbit-safe-claw-windows-x64-<version>.zip`
3. 解压后运行 `install.bat`

Linux：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新 `orbit-safe-claw-linux-x64-<version>.tar.gz`
3. 解压后运行 `bash install.sh`

如果你只想拉源码快照：

Windows：

```powershell
$zip="$env:TEMP\\orbit-safe-claw.zip"; Invoke-WebRequest "https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.zip" -OutFile $zip; Expand-Archive $zip -DestinationPath . -Force; Set-Location .\telegram-cli-bot-master; .\install.bat
```

Linux：

```bash
curl -L https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.tar.gz | tar -xz && cd telegram-cli-bot-master && bash install.sh
```

安装器会准备：

- Python / Node.js / Git 检查
- 后端依赖
- 前端依赖和构建
- `.env`

`codex` / `claude` 只检查，不自动安装；都缺失时会给出提示。

## 如何运行

Windows：

- 双击 `start.bat`
- 或终端运行 `.\start.bat`

Linux：

- 运行 `bash start.sh`

如果目录里还没有 `.env`，Windows 的 `start.bat` / `start.ps1` 会先自动运行 `install.bat` 生成配置，再继续启动。

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

说明：

- `cli` Bot 支持子 agent 和集群配置
- `assistant` Bot 走宿主管理流程，工作目录下会维护 `.assistant/`
- 当前机器只允许 1 个 `assistant` Bot

## 常用能力

- Chat：Web 聊天、流式输出、会话历史、trace 查看
- CLI Bot：子 agent 管理、非集群切换、集群模板、集群 JSON 配置、cluster MCP
- Assistant Ops：proposal 审批、patch 生成、dry-run、apply、memory、diagnostics、audit、Automation
- Files：目录浏览、预览、编辑、上传、下载
- Git：状态、diff、stage/unstage、commit、fetch/pull/push、stash/pop
- Terminal / Debug：内置终端、调试面板、系统脚本
- Plugins：插件目录扫描、配置、文件视图扩展，内置 Vivado waveform 示例

## 更新

主 Bot 设置页支持 GitHub Release 自动检查和下载更新。下载后的更新会在下次启动或重启后生效。

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
