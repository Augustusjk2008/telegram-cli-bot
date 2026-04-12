# Web Bot Frontend

手机竖屏优先的 Web Bot 前端。开发模式默认通过 Vite 代理把 `/api/*` 转发到本地 Python Web API。

前端开发在 Windows 与 Ubuntu/Debian Linux 上都可用。

## 本地启动

1. 安装依赖

```bash
npm install
```

2. 启动前端开发服务器

```bash
npm run dev
```

3. 确保后端同时运行在 `http://127.0.0.1:8765`

后端示例：

PowerShell 示例：

```powershell
$env:TELEGRAM_ENABLED = "false"
$env:WEB_ENABLED = "true"
$env:WEB_HOST = "127.0.0.1"
$env:WEB_PORT = "8765"
$env:WEB_API_TOKEN = "dev-token"
python -m bot
```

Bash 示例：

```bash
export TELEGRAM_ENABLED="false"
export WEB_ENABLED="true"
export WEB_HOST="127.0.0.1"
export WEB_PORT="8765"
export WEB_API_TOKEN="dev-token"
python -m bot
```

4. 打开 `http://127.0.0.1:3000`

登录页输入 `WEB_API_TOKEN` 即可。

## 可选环境变量

- `VITE_USE_MOCK=true`：强制前端使用 mock 数据，不请求真实后端
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=<chrome.exe>`：当 `playwright install` 下载过慢时，可临时指向本机已有 Chromium 执行 `npm run e2e`

## 常用命令

```bash
npm run clean
npm run build
npm test
```
