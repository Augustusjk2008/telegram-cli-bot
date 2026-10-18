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
$env:WEB_ENABLED = "true"
$env:WEB_HOST = "127.0.0.1"
$env:WEB_PORT = "8765"
$env:WEB_API_TOKEN = "dev-token"
python -m bot
```

Bash 示例：

```bash
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
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=<chrome.exe>`：覆盖 Playwright 浏览器路径；Windows 默认使用本机 Google Chrome，其他系统使用 Playwright Chromium
- `PLAYWRIGHT_BASE_URL=<URL>`：复用已启动的应用服务，并跳过 Playwright 自动启动开发服务器

## 浏览器自动测试

在 Windows PowerShell 中，确认应用服务已由用户启动后运行：

```powershell
$env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1:8765"
npm run e2e:smoke
```

冒烟用例验证真实登录页的输入、登录/注册切换、桌面及移动布局，并将截图写入 `test-results/`。接口响应由用例模拟。开发新功能时，在 `src/test/` 添加对应的 `*.spec.ts`，保留上述环境变量，再用 `npm run e2e -- src/test/<功能>.spec.ts` 运行。

## 常用命令

```bash
npm run clean
npm run build
npm test
```
