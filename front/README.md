# Orbit Safe Claw 前端

React / TypeScript / Vite 前端，提供桌面工作台和移动端界面。开发模式通过 Vite 将 `/api`、`/terminal`、`/debug`、`/lan-chat` 和 `/node` 请求代理到 `http://127.0.0.1:8765`，并支持 WebSocket。

以下 npm 命令均在 `front/` 目录执行；后端安装和账号初始化见仓库根目录的 README。

使用 Node.js 22.13+，以满足当前锁文件中 PDF.js 等前端依赖的要求。

## 本地开发

安装锁文件中的依赖：

```bash
npm ci
```

由用户按根目录 README 配置并手动启动后端，确认 Web API 地址为 `http://127.0.0.1:8765`。需要前端热更新时，由用户在另一个终端手动启动开发服务器：

```bash
npm run dev
```

默认访问 `http://127.0.0.1:3000`。配置了站点路径前缀时，使用带相应前缀的地址。开发脚本监听 `0.0.0.0:3000`。

登录页使用用户名和密码，注册需要注册码，也可通过 guest 只读进入。

自动化代理应复用用户已启动的应用；不得自行启动开发、预览或临时 HTTP 服务，也不得重启宿主进程。

## 可选环境变量

- `VITE_USE_MOCK=true`：选择内置 mock client，用于界面开发
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=<chrome.exe>`：覆盖 Playwright 浏览器路径；Windows 默认使用本机 Google Chrome，其他系统使用 Playwright Chromium
- `PLAYWRIGHT_BASE_URL=<URL>`：复用已启动的应用服务，并跳过 Playwright 自动启动开发服务器

## 浏览器自动测试

在 Windows PowerShell 中，确认应用服务已由用户启动后运行：

```powershell
$env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1:8765"
npm run e2e:smoke
```

冒烟用例验证真实登录页的输入、登录/注册切换、桌面及移动布局，并将截图写入 `test-results/`。接口响应由用例模拟。运行指定浏览器用例时，保留上述环境变量，再用 `npm run e2e -- src/test/<功能>.spec.ts` 运行。

运行浏览器测试前必须设置 `PLAYWRIGHT_BASE_URL`；省略该变量会触发 Playwright 配置中的 `npm run dev` 自动启动逻辑。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `npm run test:gate` | 单 worker、关闭文件并行的 Vitest 检查；可追加 `-- src/test/<文件>.test.tsx` 运行指定用例 |
| `npm test` | 使用 Vitest 默认并行方式运行单元测试 |
| `npm run lint` | 运行 `tsc --noEmit` 检查 TypeScript 类型 |
| `npm run build` | 构建到 `dist/`，生成 JS/CSS 的 Brotli、gzip 副本并检查构建体积预算 |
| `npm run check:build-budget` | 对已有构建检查体积预算及 Mermaid 懒加载 |
| `npm run verify:portable-dist` | 检查已有构建的资源、预压缩副本、第三方许可清单及本机 `/node/.../assets/` 前缀污染 |
| `npm run clean` | 删除 `dist/` 构建产物 |

`npm run build` 不执行类型检查或单元测试；验证代码修改时按影响范围分别运行相应命令。
