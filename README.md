# Web AI CLI Bridge

一个支持 Windows 与 Ubuntu/Debian Linux 的 Web AI CLI Bridge。

它把浏览器里的聊天、文件、Git 和设置操作转交给本机已经安装好的 AI Coding CLI。当前保留的 CLI 只有：

- `codex`
- `claude`

当前入口仅为 Web 页面，不再提供 Telegram 机器人入口。

## 功能概览

- Web 聊天
- 多 Bot 管理
- 支持 `cli` / `assistant` 两种 Bot 模式
- 文件浏览、预览、上传、下载
- Git 概览、diff、stage、commit、fetch/pull/push、stash
- CLI 参数配置
- 可选 Cloudflare Quick Tunnel 远程访问
- GitHub Release 自动检查与下载更新

## Assistant 约束

- 整个项目最多只能创建一个 `assistant` Bot
- `assistant` 的默认工作目录创建后不可修改
- `assistant` 的状态、proposal、upgrade、记忆都保存在 `<assistant_workdir>/.assistant/`

## 环境要求

1. Python 3.10+
2. Node.js 18+
3. 已安装至少一个本地 CLI
   可选：`codex` 或 `claude`

如果你要在 Linux 上长期部署，可以结合 [docs/linux-deployment.md](docs/linux-deployment.md) 一起使用。

## 快速开始

### Windows 一键安装

Windows 用户可以直接双击运行：

```powershell
.\install.bat
```

安装器会按顺序检查并准备：

- Python 3.10+
- Node.js 18+
- Git
- 后端依赖
- 前端依赖与构建
- `.env`

说明：

- 安装器会自动安装 Python / Node.js / Git
- `codex` / `claude` 只检查，不会自动安装
- 如果两者都没装，安装器会给出明显警告，并提示你后续如何处理

### Linux 一键安装

Ubuntu / Debian 用户可以直接运行：

```bash
bash install.sh
```

如果只想做环境检查，不执行安装：

```bash
bash install.sh --check-only
```

### 1. 安装后端依赖

```bash
python -m pip install -r requirements.txt
```

### 2. 安装并构建前端

```bash
cd front
npm install
npm run build
cd ..
```

### 3. 生成 `.env`

```powershell
Copy-Item .env.example .env
```

至少填这些字段：

```env
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=C:\Users\YourName\project

WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password
```

说明：

- `CLI_TYPE` 仅支持 `codex` / `claude`
- `CLI_PATH` 可以是命令名，也可以是绝对路径
- `WORKING_DIR` 是默认工作目录，建议设为你最常操作的项目目录

### 4. 启动

```powershell
python -m bot
```

Windows 上也可以使用：

```powershell
.\start.bat
```

说明：

- `start.bat` 会优先使用 `pwsh`，没有时回退到 `powershell`
- 启动时会请求管理员权限
- 服务会在可见控制台中直接运行，不再使用托盘图标或隐藏窗口
- 如果未配置公网穿透，控制台会提示可用的 `.env` 配置方式

Linux 上可以使用：

```bash
bash start.sh
```

## 自动更新

- 在 `.env` 中填写 `APP_UPDATE_REPOSITORY=owner/repo` 后，主 Bot 设置页可检查 GitHub Release
- 更新包下载后不会立即覆盖当前运行目录，而是在下次通过 `start.bat` / `start.ps1` / `start.sh` 启动时应用
- 下载完成后重启后生效

### 5. 打开 Web

默认访问地址：

```text
http://127.0.0.1:8765
```

登录口令使用 `.env` 里的 `WEB_API_TOKEN`。

## Web 页面

当前前端包含这些页面：

- 聊天
- 文件
- Git
- 设置
- Bot 管理

## 常用开发命令

```bash
python -m pytest tests -q
cd front && npm test
cd front && npm run build
```

## 相关文档

- [docs/linux-deployment.md](docs/linux-deployment.md)
- [docs/assistant-cron-plan.md](docs/assistant-cron-plan.md)
