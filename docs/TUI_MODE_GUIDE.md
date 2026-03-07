# TUI 模式使用指南

## 概述

TUI (Text User Interface) 模式允许通过 Web 浏览器访问完整的终端界面，支持 ANSI 转义序列和颜色渲染。这对于使用 AI coding CLI 工具（如 Claude Code、Kimi CLI）非常有用。

## 架构设计

### 核心原理

1. **原始字节流转发**: Python 后端不解析任何 ANSI 序列，直接通过 WebSocket 转发原始字节流
2. **前端渲染**: 浏览器中的 xterm.js 是完整的 VT100 终端模拟器，能正确处理所有 ANSI 信息
3. **双向通信**: 用户输入通过 WebSocket 发送到后端，CLI 输出通过 WebSocket 返回前端

### 组件说明

- `bot/handlers/tui_server.py`: WebSocket 服务器，处理 PTY/subprocess 和 WebSocket 之间的双向转发
- `bot/handlers/webcli.py`: Web 服务器和 ngrok 管理，生成 xterm.js 前端页面
- `bot/data/webcli/index.html`: 动态生成的前端页面（TUI 模式使用 xterm.js）

## 使用方法

### 1. 启动 TUI 模式

在 Telegram 中发送命令：

```
/webcli_start tui
```

或者：

```
/webcli_start --tui
```

Bot 会返回一个 ngrok 公网 URL，点击即可在浏览器中访问。

### 2. 连接到 CLI 工具

在浏览器中：

1. 在输入框中输入完整的 CLI 命令，例如：
   ```
   claude -p "hello world"
   ```

2. 点击"连接"按钮

3. xterm.js 终端会显示 CLI 的完整输出，包括颜色、进度条等

### 3. 交互式使用

- 终端支持完整的键盘输入（包括方向键、Ctrl+C 等）
- 支持复制粘贴
- 支持鼠标选择文本
- 支持窗口大小调整（自动 fit）

### 4. 停止服务

在 Telegram 中发送：

```
/webcli_stop
```

## 支持的 CLI 工具

### Claude Code

```
claude -p "implement a function to calculate fibonacci"
```

特点：
- 支持彩色输出
- 支持进度指示器
- 支持交互式确认

### Kimi CLI

```
kimi --quiet -y --thinking -p "explain async/await"
```

特点：
- 支持思考过程显示
- 支持流式输出

### Codex

```
codex exec "write a python script"
```

## 技术细节

### Windows 支持

Windows 不支持传统的 PTY，因此使用 `subprocess.PIPE` 模式：

```python
process = subprocess.Popen(
    command,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"}
)
```

关键环境变量：
- `FORCE_COLOR=1`: 强制启用颜色输出
- `TERM=xterm-256color`: 设置终端类型

### Unix/Linux 支持

Unix 系统使用真正的 PTY：

```python
import pty
master_fd, slave_fd = pty.openpty()
process = subprocess.Popen(
    command,
    stdin=slave_fd,
    stdout=slave_fd,
    stderr=slave_fd,
    preexec_fn=os.setsid
)
```

### WebSocket 协议

初始化消息（客户端 → 服务器）：

```json
{
  "command": ["claude", "-p", "hello"],
  "cwd": "/path/to/workdir"
}
```

数据传输：
- 服务器 → 客户端: 原始字节流（`websocket.send(bytes)`）
- 客户端 → 服务器: 用户输入（键盘事件转换为字节）

### xterm.js 配置

```javascript
const term = new Terminal({
    cursorBlink: true,
    fontSize: 14,
    fontFamily: '"Cascadia Code", "Courier New", monospace',
    theme: {
        background: '#0c0c0c',
        foreground: '#cccccc',
        // ... 完整的颜色主题
    }
});
```

## 故障排查

### 连接失败

1. 检查 TUI WebSocket 服务器是否启动（端口 8081）
2. 检查防火墙设置
3. 查看 bot 日志：`logger.info` 输出

### 颜色不显示

1. 确保 CLI 工具支持颜色输出
2. 检查环境变量 `FORCE_COLOR=1` 是否设置
3. 某些 CLI 工具需要额外参数（如 `--color=always`）

### 输入无响应

1. 检查 WebSocket 连接状态
2. 查看浏览器控制台错误
3. 确认 CLI 进程是否正常运行

## 性能优化

### 缓冲区大小

当前设置为 1024 字节：

```python
data = await asyncio.get_event_loop().run_in_executor(
    None, process.stdout.read, 1024
)
```

可根据实际情况调整。

### 网络延迟

ngrok 会引入一定延迟，本地测试可以直接访问 `http://127.0.0.1:8080`（需要修改前端 WebSocket URL）。

## 安全注意事项

1. **命令注入**: 当前实现信任客户端输入，生产环境需要添加命令白名单
2. **认证**: ngrok URL 是公开的，建议添加认证机制
3. **资源限制**: 需要限制并发连接数和进程数量

## 未来改进

- [ ] 添加命令历史记录
- [ ] 支持多会话管理
- [ ] 添加文件上传/下载功能
- [ ] 支持终端录制和回放
- [ ] 添加用户认证
- [ ] 支持自定义主题
