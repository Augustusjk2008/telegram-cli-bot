# Telegram CLI Bridge

一个面向 Windows 的 Telegram / Web 双入口 AI CLI Bridge。

它可以把你在 Telegram 或 Web 页面里发出的消息，转交给本机已经安装好的 AI Coding CLI，例如：

- `codex`
- `claude`
- `kimi`

适合这样的使用场景：

- 想在 Telegram 里直接和本机 CLI 对话
- 想在网页里统一管理聊天、文件、Git 和设置
- 想把自己的电脑变成一个长期运行的个人 AI 助手入口

## 功能概览

- Telegram 聊天入口
- Web 管理界面
- 支持 `codex` / `claude` / `kimi`
- 支持文件浏览、上传、下载、查看
- Web 端支持 Git 概览与常见操作
- 支持一个主 Bot + 多个托管子 Bot
- 可选语音转文字
- 可选 Cloudflare Quick Tunnel 手机公网访问

## 安装前准备

这是一个 Windows 优先项目，下面的命令示例使用 PowerShell。

开始前请准备好：

1. Python
   建议使用 Python 3.10 及以上，并确保 `python` 命令可用。
2. Telegram Bot Token
   到 `@BotFather` 创建机器人，拿到 `TELEGRAM_BOT_TOKEN`。
3. 至少一个本地 CLI
   例如 `codex`、`claude` 或 `kimi`。请先确认它已经安装完成，并且你可以在终端里直接运行它。
4. Node.js
   只有在你要使用 Web 界面时才需要。仅使用 Telegram 可以不装。

## 5 分钟快速开始

### 1. 安装 Python 依赖

在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
```

### 2. 新建 `.env`

在仓库根目录新建一个 `.env` 文件，先填最小配置：

```env
TELEGRAM_BOT_TOKEN=填入你的 Telegram Bot Token
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=C:\Users\YourName\project

TELEGRAM_ENABLED=true
WEB_ENABLED=false

ALLOWED_USER_IDS=
```

说明：

- `CLI_TYPE` 可选：`codex` / `claude` / `kimi`
- `CLI_PATH` 是 CLI 可执行文件路径
  如果该命令已经在系统 `PATH` 中，直接写 `codex` 这类命令名即可
  如果不在 `PATH` 中，请写绝对路径
- `WORKING_DIR` 是默认工作目录，建议填你最常操作的项目目录
- `ALLOWED_USER_IDS` 留空表示任何能找到这个机器人账号的人都可以使用
  正式使用时建议填你自己的 Telegram 数字用户 ID

### 3. 启动

直接启动：

```powershell
python -m bot
```

或者在 Windows 上用托盘方式启动：

```powershell
.\start.bat
```

### 4. 开始使用

在 Telegram 里打开你的机器人，先发送：

```text
/start
```

然后就可以直接发普通文本消息，例如：

```text
帮我看看当前目录里有哪些 Python 文件
```

## Telegram 使用方式

Telegram 是最直接的入口。只要 Bot 已启动，你就可以像聊天一样驱动本机 CLI。

### 常用命令

- `/start`：显示欢迎信息
- `/reset`：重置当前会话
- `/kill`：终止当前运行中的任务
- `/cd <路径>`：切换工作目录
- `/pwd`：查看当前目录
- `/ls`：列出当前目录内容
- `/files`：打开文件浏览
- `/history`：查看会话历史
- `/upload`：查看上传文件说明
- `/download <文件>`：下载文件
- `/cat <文件>`：查看文件内容
- `/head <文件>`：查看文件开头
- `/exec <命令>`：执行 shell 命令
- `/rm <路径>`：删除文件
- `/codex_status`：查看 Codex 相关状态

### 使用建议

- 平时直接发自然语言即可，不一定要用命令
- 如果 CLI 没有在系统 `PATH` 里，优先修正 `.env` 里的 `CLI_PATH`
- 正式使用前建议限制 `ALLOWED_USER_IDS`

## Web 使用方式

如果你想在浏览器里使用聊天、文件、Git 和设置页面，可以启用 Web 界面。

### 1. 安装前端依赖并构建

首次启用 Web 前，先构建前端：

```powershell
cd front
npm install
npm run build
```

### 2. 在 `.env` 中启用 Web

把下面这些配置加入 `.env`：

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=改成你自己的网页登录口令
```

如果你想同时开启 Telegram 和 Web，请保持：

```env
TELEGRAM_ENABLED=true
WEB_ENABLED=true
```

### 3. 启动服务

同时启用 Telegram 和 Web：

```powershell
python -m bot
```

或者：

```powershell
.\start.bat
```

如果你只想开 Web，不开 Telegram：

```env
TELEGRAM_ENABLED=false
WEB_ENABLED=true
```

然后可以这样启动：

```powershell
python -m bot
```

或者使用仓库自带的 Web 模式启动器：

```powershell
.\start.bat web
```

### 4. 打开页面

在浏览器访问：

```text
http://127.0.0.1:8765
```

登录口令就是 `WEB_API_TOKEN`。

### Web 里能做什么

- Chat：网页聊天
- Files：文件浏览与预览
- Git：查看改动、暂存、提交、拉取、推送等
- Settings：参数、隧道、运行状态等设置

## 推荐配置示例

如果你想同时使用 Telegram 和 Web，一个比较常见的 `.env` 例子如下：

```env
TELEGRAM_BOT_TOKEN=填入你的 Telegram Bot Token
ALLOWED_USER_IDS=123456789

CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=C:\Users\YourName\project

TELEGRAM_ENABLED=true
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password
```

## 可选功能

### 语音转文字

项目支持 Telegram 语音消息转文字，但这是可选功能。

如果你要启用它，还需要额外准备：

- `openai-whisper`
- `pydub`
- FFmpeg

相关配置项：

```env
WHISPER_ENABLED=true
WHISPER_MODEL=small
WHISPER_LANGUAGE=zh
WHISPER_DEVICE=cpu
```

如果这些依赖没有装，语音功能会被跳过，文字消息功能不受影响。

### 手机公网访问 Web

如果你想在手机上通过公网打开 Web 页面，可以使用 Cloudflare Quick Tunnel。

先确保：

- 你已经完成 Web 前端构建
- 你本机安装了 `cloudflared`

然后在 `.env` 里加入：

```env
WEB_ENABLED=true
WEB_TUNNEL_MODE=cloudflare_quick
WEB_TUNNEL_AUTOSTART=true
WEB_TUNNEL_CLOUDFLARED_PATH=D:\Programs\cloudflared\cloudflared.exe
```

启动后，Web 设置页会显示公网地址。

如果你已经有自己的固定公网地址，也可以直接配置：

```env
WEB_PUBLIC_URL=https://your-domain.example.com
```

### 多 Bot

仓库支持一个主 Bot 加多个托管子 Bot，配置文件是根目录的 `managed_bots.json`。

如果你只是自己单人使用，可以先忽略这部分，先把主 Bot 跑起来。

## 常见问题

### 1. 启动时报错“请设置 TELEGRAM_BOT_TOKEN”

说明 `.env` 里的 `TELEGRAM_BOT_TOKEN` 没填对，或者程序没有读到 `.env`。

优先检查：

- `.env` 是否放在仓库根目录
- `TELEGRAM_BOT_TOKEN` 是否真实有效

### 2. Telegram 能发消息，但 CLI 没反应

优先检查：

- 你选择的 CLI 是否真的已经安装
- 终端里是否能直接运行 `codex` / `claude` / `kimi`
- `.env` 里的 `CLI_PATH` 是否正确

### 3. Web 打不开或页面空白

优先检查：

- 是否已经执行过 `cd front && npm install && npm run build`
- `.env` 里是否启用了 `WEB_ENABLED=true`
- 访问地址是否正确，例如 `http://127.0.0.1:8765`

### 4. 为什么不能直接双击 `front/dist/index.html`

因为这个前端不是离线单文件页面。

它依赖：

- `/assets/...` 静态资源
- 同源 `/api/...` 接口

所以正确打开方式是让 Python Web 服务托管它，然后通过 `http://127.0.0.1:8765` 或公网地址访问。

### 5. 我想同时开 Telegram 和 Web，应该怎么启动

把 `.env` 设成：

```env
TELEGRAM_ENABLED=true
WEB_ENABLED=true
```

然后使用：

```powershell
python -m bot
```

或者：

```powershell
.\start.bat
```

不要使用 `.\start.bat web`，因为那个模式会强制关闭 Telegram。

### 6. Telegram 网络不通怎么办

可以在 `.env` 中配置代理：

```env
PROXY_URL=http://127.0.0.1:7890
```

也支持 `https://` 和 `socks5://` 形式。

## 测试与开发

如果你是在修改项目本身，而不是仅仅把它跑起来，常用命令如下：

```powershell
python -m pytest tests -q
```

```powershell
cd front
npm test
```

## 说明

- 这是一个 Windows 优先项目
- 用户可见文本目前以中文为主
- 仓库里即使存在 `venv/`，也不要默认假设它在你的机器上可直接使用
- 最稳妥的方式仍然是使用你当前机器上的 Python 环境重新安装依赖
