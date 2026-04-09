# Telegram CLI Bridge

Windows 上运行的 Telegram / Web 双入口 AI CLI Bridge。

当前仓库的 Web 端有两种常见用法：

1. 本地开发：`Vite + aiohttp` 联调
2. 手机公网访问：由 Python Web 服务托管前端静态资源，再用 Cloudflare Quick Tunnel 暴露同一个地址

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

说明：

- 前端开发服务器会把 `/api/*` 代理到 `http://127.0.0.1:8765`
- `TELEGRAM_ENABLED=false` 时会进入本地 `Web only` 模式，不启动 Telegram 轮询
- 如果要联调真实 CLI，请确认 `codex` / `kimi` / `claude` 至少有一个已在本机可执行

## Cloudflare Quick Tunnel

### 推荐用法

如果你要让手机通过公网访问，推荐不要继续使用 `npm run dev` 暴露 Vite。

推荐流程是：

1. 先把前端打包成 `front/dist`
2. 让 Python Web 服务同时托管前端静态资源和 `/api`
3. 由 Python 进程内置的 `cloudflared` support 把 `http://127.0.0.1:8765` 暴露出去

这样手机只访问一个公网 URL，前后端同源，不需要额外处理前端代理、CORS、两个公网地址或手机端切换地址。

### 前后端各自怎么用

前端：

- 先执行 `npm run build`
- 产物会落到 `front/dist`
- Python 后端启动后会自动托管 `front/dist` 下的静态资源和 `index.html`
- 手机访问 tunnel URL 时，实际拿到的是后端托管的前端页面

后端：

- 启用 `WEB_ENABLED=true`
- 配置 `WEB_TUNNEL_MODE=cloudflare_quick`
- 配置 `WEB_TUNNEL_AUTOSTART=true`
- 配置 `WEB_TUNNEL_CLOUDFLARED_PATH` 指向 `cloudflared.exe`，或者把 `cloudflared` 放进系统 `PATH`
- 启动 `python -m bot`
- 后端启动完成后会尝试自动拉起 Quick Tunnel，并在 Web 设置页的“公网访问”区块显示当前状态和公网 URL

### 推荐启动步骤

先构建前端：

```powershell
cd front
npm install
npm run build
```

注意：

- 不要直接双击 `front/dist/index.html`
- 也不要用 `file:///.../front/dist/index.html` 方式打开
- 当前构建产物默认引用 `/assets/...`，并且前端运行时还要请求同源 `/api/...`
- 所以它必须由 `http://` 服务托管，不能按离线 HTML 文件那样直接打开

然后回到仓库根目录启动后端：

```powershell
$env:TELEGRAM_ENABLED = "false"
$env:WEB_ENABLED = "true"
$env:WEB_HOST = "127.0.0.1"
$env:WEB_PORT = "8765"
$env:WEB_API_TOKEN = "dev-token"
$env:WEB_TUNNEL_MODE = "cloudflare_quick"
$env:WEB_TUNNEL_AUTOSTART = "true"
$env:WEB_TUNNEL_CLOUDFLARED_PATH = "D:\Programs\cloudflared\cloudflared.exe"
python -m bot
```

启动完成后，正确的打开方式是：

- 本机浏览器访问 `http://127.0.0.1:8765`
- 或者手机访问 Cloudflare Tunnel 给出的 `https://*.trycloudflare.com`

或者直接把这些值写进根目录 `.env` 后启动：

```powershell
python -m bot
```

如果你已经把 Web 相关配置写进根目录 `.env`，也可以直接运行：

```powershell
start.bat web
```

它会以 `web` 模式启动托盘脚本，并在启动 Python 前临时设置：

- `TELEGRAM_ENABLED=false`
- `WEB_ENABLED=true`

手机端使用方式：

- 打开 Web 设置页里的“公网访问”
- 复制当前 `https://*.trycloudflare.com`
- 手机浏览器访问这个地址
- 登录口令使用 `WEB_API_TOKEN`

### 当前支持的 Tunnel 配置项

- `WEB_ENABLED`
- `WEB_HOST`
- `WEB_PORT`
- `WEB_API_TOKEN`
- `WEB_PUBLIC_URL`
- `WEB_TUNNEL_MODE`
- `WEB_TUNNEL_AUTOSTART`
- `WEB_TUNNEL_CLOUDFLARED_PATH`

说明：

- `WEB_TUNNEL_MODE=cloudflare_quick` 会启用内置 Quick Tunnel
- `WEB_TUNNEL_AUTOSTART=true` 会在 Web 服务启动后自动拉起 tunnel
- `WEB_TUNNEL_CLOUDFLARED_PATH` 需要指向 `cloudflared.exe`，不是目录
- 如果设置了 `WEB_PUBLIC_URL`，当前会进入“手工公网地址”模式，不会自动拉起 Quick Tunnel

### 如果你还想继续用 Vite 开发服务器

这是开发态玩法，不是推荐的手机公网访问方式。

当前内置的 Quick Tunnel 是挂在 Python Web 服务上的，也就是 `http://127.0.0.1:8765`，不是挂在 `Vite dev server` 的 `http://127.0.0.1:3000` 上。

所以：

- 如果你继续用 `npm run dev`
- 又想让手机看到 Vite 的热更新页面
- 你需要自己额外运行一个单独的 `cloudflared tunnel --url http://127.0.0.1:3000`

这时前端的 `/api` 仍会由 Vite 代理到本机 `8765`，所以手机访问的是“Vite 的 tunnel URL”，不是后端内置 tunnel URL。

换句话说：

- 生产/推荐链路：一个 tunnel，指向 Python Web 服务，后端托管前端
- 开发/调试链路：一个单独的 tunnel，指向 Vite；Vite 再反向代理 `/api` 到本机后端

## 为什么 `dist/index.html` 不能直接打开

如果你直接打开 `front/dist/index.html`，浏览器地址会变成 `file:///.../front/dist/index.html`。

这时会同时遇到两个问题：

1. 构建产物里的资源路径是 `/assets/...`
   这在 `file://` 场景下会被解释成类似 `file:///C:/assets/...`
2. 前端运行时调用的是同源 `/api/...`
   这要求页面本身必须运行在 `http://127.0.0.1:8765` 或某个真实域名下

所以当前项目的正确理解是：

- `npm run build` 只是产出静态文件
- 真正提供访问入口的是 Python Web 服务
- 不是“构建后双击 HTML 就能单文件运行”的离线页面
