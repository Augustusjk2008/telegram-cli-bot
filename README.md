# Telegram CLI Bridge

Windows 上运行的 Telegram / Web 双入口 AI CLI Bridge。当前仓库已经支持在本地以 `Vite + aiohttp` 的方式联调 Web 端，不需要先接入 cloudflared。

## 本地联调

后端：

```powershell
$env:TELEGRAM_ENABLED = "false"
$env:WEB_ENABLED = "true"
$env:WEB_HOST = "127.0.0.1"
$env:WEB_PORT = "8765"
$env:WEB_API_TOKEN = "dev-token"
$env:CLI_TYPE = "codex"
$env:CLI_PATH = "codex"
python -m bot
```

前端：

```powershell
cd front
npm install
npm run dev
```

打开 `http://127.0.0.1:3000`，登录口令填上面的 `WEB_API_TOKEN`。

## 说明

- 前端开发服务器会把 `/api/*` 代理到 `http://127.0.0.1:8765`
- `TELEGRAM_ENABLED=false` 时会进入本地 `Web only` 模式，不启动 Telegram 轮询
- 如果要联调真实 CLI，请确认 `codex` / `kimi` / `claude` 至少有一个已在本机可执行
