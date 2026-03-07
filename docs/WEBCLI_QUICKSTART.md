# Web CLI 快速开始

## 概述

Web CLI 模式允许你通过 Telegram bot 启动一个 web 服务器，并通过 ngrok 暴露到公网，从而在手机浏览器中访问一个简单的 web 界面。

## 前置条件

1. **ngrok 已安装并配置**
   - 下载 ngrok: https://ngrok.com/download
   - 配置 authtoken: `ngrok config add-authtoken YOUR_TOKEN`

2. **创建一个新的 Telegram Bot**
   - 通过 @BotFather 创建新 bot
   - 获取 bot token

## 配置步骤

### 方法 1: 通过主 bot 添加（推荐）

1. 启动主 bot: `python -m bot`

2. 在 Telegram 中发送命令:
   ```
   /bot_add webcli YOUR_BOT_TOKEN webcli
   ```

### 方法 2: 手动编辑配置文件

1. 编辑 `managed_bots.json`:
   ```json
   {
     "bots": [
       {
         "alias": "webcli",
         "token": "YOUR_BOT_TOKEN",
         "cli_type": "claude",
         "cli_path": "claude",
         "working_dir": "C:\\Users\\YourName\\project",
         "enabled": true,
         "bot_mode": "webcli"
       }
     ]
   }
   ```

2. 重启 bot: `python -m bot`

## 使用方法

1. **启动 Web CLI**
   ```
   /start
   ```
   Bot 会启动 web 服务器和 ngrok，并返回一个公网 URL

2. **查看状态**
   ```
   /status
   ```
   查看 web 服务器和 ngrok 的运行状态

3. **停止服务**
   ```
   /stop
   ```
   停止 web 服务器和 ngrok

## 架构说明

```
Telegram Bot (webcli mode)
    ↓
启动 Python HTTP Server (端口 8080)
    ↓
启动 ngrok 隧道
    ↓
返回公网 URL 给用户
    ↓
用户在手机浏览器中访问
```

## 当前功能

- ✅ 启动本地 web 服务器
- ✅ 通过 ngrok 暴露到公网
- ✅ 发送 URL 给 Telegram 用户
- ✅ 显示简单的欢迎页面

## 后续扩展

- [ ] 添加交互式终端界面
- [ ] 支持命令执行
- [ ] 支持文件上传/下载
- [ ] 支持实时日志查看
- [ ] 支持 WebSocket 实时通信

## 注意事项

1. **安全性**: ngrok 免费版的 URL 是公开的，任何人都可以访问。建议添加身份验证。

2. **端口占用**: 默认使用 8080 端口，如果被占用需要修改代码。

3. **ngrok 限制**: 免费版有连接数和带宽限制。

4. **关闭页面**: 可以关闭 ngrok 的 web 界面（http://127.0.0.1:4040），bot 会通过 API 获取 URL。

## 故障排查

### ngrok 启动失败
- 检查 authtoken 是否配置: `ngrok config check`
- 检查 ngrok 是否在 PATH 中: `ngrok version`

### 无法获取 URL
- 等待 3-5 秒后重试 `/status`
- 检查 ngrok API 端口 4040 是否可访问

### 端口被占用
- 修改 `bot/handlers/webcli.py` 中的端口号
- 或者关闭占用 8080 端口的程序
