# Mobile Terminal Redesign

日期：2026-04-10

## 目标

优化 Web 终端页的两类问题：

1. 流式输出尽量接近真实终端，正确处理 ANSI 控制序列、`\r` 覆盖刷新和常见终端输出行为。
2. 手机和桌面共用一套终端页面，但交互设计按手机“看持续输出为主、输入为辅”的使用习惯优化。

## 用户确认的约束

- 手机最常见场景是看长时间滚动输出，输入命令是次要但必须可用。
- 流式输出目标选 A 档：尽量接近真实终端，而不是只做按行追加。
- 手机和桌面共用同一套终端页面，不拆成两套产品。
- 不重复造轮子，终端流式解析和 ANSI/控制序列处理优先使用成熟方案。
- 终端页继续作为当前 Web 应用内的一个 tab，而不是独立浏览器页面或 iframe 应用。

## 现状

- [front/src/screens/TerminalScreen.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/TerminalScreen.tsx) 当前通过 iframe 加载后端拼接的终端 HTML。
- [bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py) 当前同时承担终端 HTML 生成、WebSocket 接入和 PTY 启动逻辑。
- [bot/handlers/tui_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py) 已有可复用的 Windows PTY / shell 启动封装。
- 当前手机体验是桌面终端的最小移植版：
  - 终端输出主要依赖内嵌页面逻辑。
  - 手机触控和虚拟键盘适配较弱。
  - 用户查看长输出时，缺少明确的“跟随输出 / 返回最新位置”机制。

## 已选方案

### 1. 前端终端内核

- 去掉 iframe 方案，在 React 页面内直接嵌入 `xterm.js`。
- 使用官方包而不是手写解析：
  - `@xterm/xterm`
  - `@xterm/addon-attach`
  - `@xterm/addon-fit`
- 前端只负责：
  - 创建终端实例
  - 将 WebSocket 连接附着到终端
  - 管理移动端交互状态
  - 管理视口和布局
- 前端不负责自己解析 ANSI、`\r`、进度条刷新或其他终端控制序列。

### 2. 后端职责边界

- 保留 [bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py) 中的 `/terminal/ws` 路由。
- 保留 [bot/handlers/tui_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py) 中的 PTY/shell 启动能力。
- 删除或退役后端拼接终端 HTML 的逻辑，使后端职责收敛为：
  - WebSocket 鉴权
  - 启动 shell / PTY
  - 原始字节双向转发
  - 生命周期清理
- 前后端协议尽量简单：
  - 默认传输原始终端流
  - 少量控制消息只保留初始化、可选 resize 和连接状态

### 3. 页面与保活策略

- [front/src/app/App.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/app/App.tsx) 继续保留“终端 tab 切换时不卸载”的策略。
- 终端会话仍然是全局共享的一份。
- 首次进入终端页或手动点“重建终端”时，按当前选中 bot 的 `working_dir` 启动。
- 从终端页切到聊天、文件、Git、设置后，终端会话继续存在；重新切回时直接恢复原会话视图。

## 手机优先交互

### 1. 布局

- 手机和桌面共用同一套页面组件。
- 手机默认采用“输出优先”布局：
  - 顶部保留精简状态栏
  - 终端视口占据主要高度
  - 底部固定触控工具条
- 桌面沿用更传统的终端页布局，但不分叉为另一套实现。

### 2. 输出跟随

- 当用户停留在输出底部时，终端自动跟随最新输出。
- 当用户手动上滑查看历史时，暂停自动滚动。
- 页面出现显式“回到最新输出”入口，用于恢复自动跟随。
- 这个逻辑只影响视口，不影响 shell 会话本身。

### 3. 触控输入

- 手机不依赖“像桌面一样直接在终端区域里精确操作文本光标”。
- 底部触控工具条至少包含：
  - `Ctrl+C`
  - `Tab`
  - 方向键
  - `Esc`
  - 显示/隐藏键盘
  - 回到最新输出
- 所有操作按钮使用大触控面积，并适配安全区。

### 4. 键盘与视口

- 使用浏览器视口变化信号重新 fit 终端区域，减少手机虚拟键盘弹出时的遮挡和跳动。
- 页面不依赖 iframe 内部高度推断。
- 当前目录、连接状态和重建操作保留在顶部状态栏。

## 组件拆分

### 前端

- [front/src/screens/TerminalScreen.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/TerminalScreen.tsx)
  - 负责终端页布局、状态栏、触控工具条、跟随输出状态。
- 新增终端连接封装，例如 `front/src/services/terminalSession.ts`
  - 负责创建 WebSocket、绑定 xterm addon、发送控制键。
- [front/src/app/App.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/app/App.tsx)
  - 继续负责 tab 级保活和当前 bot 的 workdir 注入。

### 后端

- [bot/web/server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py)
  - 负责 `/terminal/ws` 鉴权和接线。
- [bot/handlers/tui_server.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/tui_server.py)
  - 继续负责 PTY 与 shell 进程封装。

## 错误处理

- WebSocket 连接失败时，终端页状态栏明确显示失败状态，并提供重建终端入口。
- PTY 创建失败时，前端展示可读错误，不让页面静默空白。
- 重建终端只重建当前共享终端会话，不影响其他 Web 页面。
- 手机上如果键盘或触控条导致视口变化异常，优先保证“能看到最新输出”和“能发送 Ctrl+C”。

## 测试

- 前端测试新增覆盖：
  - 终端 tab 保活
  - 手机布局下工具条显示
  - 点击控制键会写入 WebSocket
  - 用户离开底部后暂停自动跟随，点击按钮后恢复
- 后端测试新增覆盖：
  - `/terminal/ws` 鉴权
  - 原始字节流透传
  - PTY 关闭和清理
  - 可选 resize / 控制消息不会破坏会话
- 验证命令至少包括：
  - `python -m pytest tests/test_web_api.py tests/test_tui_server.py -q`
  - `cd front && npm test`
  - `cd front && npm run build`

## 不在本次范围

- 不保证 `vim`、`less`、`htop` 等复杂全屏 TUI 在手机上的体验达到桌面级。
- 不在本次实现里自研终端控制序列解析器。
- 不单独做一套移动端终端产品或另起独立 Web 应用。

## 参考依据

- 官方 `xterm.js` 包：<https://www.npmjs.com/package/@xterm/xterm>
- 官方 Attach addon：<https://www.npmjs.com/package/@xterm/addon-attach>
- 官方 Fit addon：<https://www.npmjs.com/package/@xterm/addon-fit>
- 旧 `xterm-addon-attach` 已弃用：<https://www.npmjs.com/package/xterm-addon-attach>
- xterm.js 官方仓库中仍存在移动端触控相关 open issue，说明手机交互需要显式设计，而不是直接套桌面终端：
  - <https://github.com/xtermjs/xterm.js/issues/5382>
  - <https://github.com/xtermjs/xterm.js/issues/3727>
