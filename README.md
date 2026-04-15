# Orbit Safe Claw 🦞

一个把本地 `codex` / `claude` CLI 封装成网页控制台的项目，电脑和手机浏览器都能直接访问，不需要额外 App。

## 环境要求

- Windows 10 / 11
- Ubuntu / Debian Linux

## 如何下载与安装

推荐使用 GitHub Releases 的正式发布包：

Windows：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新的 `orbit-safe-claw-windows-x64-<version>.zip`
3. 解压后进入目录，运行 `install.bat`

Linux：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新的 `orbit-safe-claw-linux-x64-<version>.tar.gz`
3. 解压后进入目录，运行 `bash install.sh`

如果你只是想直接拉取最新源码快照，也可以继续用一行命令：

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

如果目录里还没有 `.env`，Windows 的 `start.bat` / `start.ps1` 会先自动运行 `install.bat` 生成配置，再继续启动。

默认 Web 绑定地址是 `0.0.0.0:8765`；本机访问可使用 `http://127.0.0.1:8765`，登录口令使用 `.env` 里的 `WEB_API_TOKEN`。

如果 `.env` 里配置的 `WEB_PORT` 已被占用，启动时会自动尝试 `+1` 直到找到可用端口；控制台、健康检查接口和 Cloudflare quick tunnel 都会同步使用这个实际端口。

如果启用了 `WEB_TUNNEL_MODE=cloudflare_quick` 且 tunnel 成功拉起，控制台会额外打印公网地址二维码，方便手机直接扫码打开。

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
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=change-this-password
```

主 Bot 设置页支持 GitHub Release 自动检查与下载更新，下载后的更新会在下次启动或重启后生效。首次安装生成的 `.env` 已默认写入 `APP_UPDATE_REPOSITORY=Augustusjk2008/telegram-cli-bot`；如果你使用自己的 GitHub Releases 仓库，改成对应的 `owner/repo` 即可。

常用开发命令：

```bash
python -m pytest tests -q
cd front && npm test
cd front && npm run build
```
