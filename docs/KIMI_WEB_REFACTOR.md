# Kimi Web Bot 重构说明

## 变更概述

将原有的 PowerShell + ngrok 转发方案改为专门针对 Kimi Web 的实现。新方案直接启动 `kimi web` 命令，并通过 ngrok 将 Kimi 的 Web UI 转发到公网。

## 主要变更

### 1. 新增文件

- **`bot/handlers/kimi_web.py`** - 新的 Kimi Web 模式处理器
  - `handle_kimi_web_start()` - 启动 Kimi Web + ngrok
  - `handle_kimi_web_stop()` - 停止服务
  - `handle_kimi_web_status()` - 查看状态
  - `_parse_kimi_output()` - 解析 Kimi 启动输出，提取本地 URL
  - `_start_kimi_web()` - 启动 Kimi Web 进程
  - `_start_ngrok()` - 启动 ngrok 隧道

- **`test_kimi_web_parse.py`** - 测试 Kimi 输出解析功能

### 2. 修改文件

- **`bot/handlers/__init__.py`**
  - 将 `from .webcli import ...` 改为 `from .kimi_web import ...`
  - 更新 `_register_webcli_handlers()` 使用新的 Kimi Web handlers
  - 更新日志信息为 "注册 Kimi Web 模式 handlers"

- **`CLAUDE.md`**
  - 更新多机器人系统说明，添加 webcli (Kimi Web) 模式
  - 更新 Handler Structure 部分，详细说明三种模式的区别

- **`docs/WEBCLI_IMPLEMENTATION.md`**
  - 更新文档标题为 "Kimi Web Bot 实现总结"
  - 更新架构流程图，反映新的实现方式
  - 标记废弃的文件（webcli.py, tui_server.py, combined_server.py）

### 3. 废弃但保留的文件

以下文件不再使用，但暂时保留以供参考：
- `bot/handlers/webcli.py` - 旧的 PowerShell 转发实现
- `bot/handlers/tui_server.py` - TUI WebSocket 服务器
- `bot/handlers/combined_server.py` - 组合服务器

## 技术实现

### 工作流程

1. **启动 Kimi Web**
   ```bash
   kimi web
   ```
   输出示例：
   ```
   +==============================================================+
   |               █▄▀ █ █▀▄▀█ █   █▀▀ █▀█ █▀▄ █▀▀                |
   |               █ █ █ █ ▀ █ █   █▄▄ █▄█ █▄▀ ██▄                |
   |                                                              |
   |                  WEB UI (Technical Preview)                  |
   |                                                              |
   |--------------------------------------------------------------|
   |                                                              |
   |   ➜  Local    http://127.0.0.1:5494                          |
   |                                                              |
   +==============================================================+
   ```

2. **解析本地 URL**
   - 使用正则表达式 `r'➜\s+Local\s+(http://127\.0\.0\.1:\d+)'` 提取 URL
   - 最多等待 10 秒，每 100ms 检查一次输出

3. **启动 ngrok 隧道**
   ```bash
   ngrok http http://127.0.0.1:5494
   ```
   - 通过 ngrok API (http://127.0.0.1:4040/api/tunnels) 获取公网 URL
   - 最多重试 5 次，每次间隔 2 秒

4. **返回公网 URL**
   - 通过 Telegram 消息返回可点击的公网链接
   - 用户可以在任何设备上访问 Kimi Web UI

### 架构对比

**旧方案（PowerShell 转发）：**
```
Telegram Bot → TUI Server (WebSocket) → PowerShell → ngrok → 公网
```
问题：
- 需要维护复杂的 WebSocket 服务器
- 需要处理 PTY/PIPE 模式切换
- 需要处理中文编码问题
- 只能转发 PowerShell，不够灵活

**新方案（Kimi Web 直接转发）：**
```
Telegram Bot → kimi web → ngrok → 公网
```
优势：
- 简单直接，只需启动 kimi web 命令
- 利用 Kimi 自带的 Web UI，功能完整
- 不需要维护 WebSocket 服务器
- 不需要处理编码问题

## 使用方法

### 配置 Bot

在 `managed_bots.json` 中添加或修改 bot 配置：

```json
{
  "bot_id": "your_bot_token",
  "bot_mode": "webcli",
  "cli_type": "kimi",
  "working_directory": "C:\\your\\project\\path"
}
```

### 启动服务

1. 在 Telegram 中向 bot 发送 `/start`
2. Bot 会自动启动 Kimi Web 和 ngrok
3. 返回公网 URL，点击即可访问

### 停止服务

发送 `/stop` 命令停止所有服务

### 查看状态

发送 `/status` 命令查看当前状态

## 测试

运行测试脚本验证 URL 解析功能：

```bash
python test_kimi_web_parse.py
```

## 依赖

- Kimi CLI (`kimi` 命令可用)
- ngrok (已配置 authtoken)
- Python 3.8+

## 注意事项

1. 确保 Kimi CLI 已正确安装并可以执行 `kimi web`
2. 确保 ngrok 已配置 authtoken
3. 每次只能启动一个 Kimi Web 实例
4. ngrok 免费版有连接数限制
5. 停止服务时会自动清理所有进程
