# Orbit Safe Claw 🦞

一个把本地 `codex` / `claude` CLI 封装成网页控制台的项目，电脑和手机浏览器都能直接访问，不需要额外 App。

## 环境要求

- Windows 10 / 11
- Ubuntu / Debian Linux

## 如何下载与安装

Windows：

```powershell
$zip="$env:TEMP\\orbit-safe-claw.zip"; Invoke-WebRequest "https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.zip" -OutFile $zip; Expand-Archive $zip -DestinationPath . -Force; Set-Location .\telegram-cli-bot-master; .\install.bat
```

Linux：

```bash
curl -L https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.tar.gz | tar -xz && cd telegram-cli-bot-master && bash install.sh
```

## 如何运行

Windows：

- 双击 `start.bat`
- 或在终端运行 `.\start.bat`

Linux：

- 运行 `bash start.sh`

默认 Web 地址是 `http://127.0.0.1:8765`，登录口令使用 `.env` 里的 `WEB_API_TOKEN`。

## 其它说明

当前仅保留两类本地 CLI 接入：

- `codex`
- `claude`

当前运行入口仅为 Web，不再包含 Telegram 机器人入口。

安装器会按顺序检查并安装或准备这些内容：

- Python 3.10+
- Node.js 18+
- Git
- 后端依赖
- 前端依赖与构建
- `.env`

`codex` / `claude` 只做检查，不会自动安装；如果两者都没装，安装器会给出明显警告和安装提示。

首次安装后至少需要在 `.env` 中确认这些配置：

```env
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=C:\Users\YourName\project
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password
```

主 Bot 设置页支持 GitHub Release 自动检查与下载更新；在 `.env` 中填写 `APP_UPDATE_REPOSITORY=owner/repo` 后即可启用。

常用开发命令：

```bash
python -m pytest tests -q
cd front && npm test
cd front && npm run build
```

相关文档：

- [docs/linux-deployment.md](docs/linux-deployment.md)
- [docs/assistant-cron-plan.md](docs/assistant-cron-plan.md)
