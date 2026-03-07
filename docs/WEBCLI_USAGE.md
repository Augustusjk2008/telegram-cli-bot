# Web CLI Bot 使用示例

## 快速开始

### 1. 通过主 bot 添加 webcli bot

在 Telegram 中向主 bot 发送：

```
/bot_add webcli 7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw webcli
```

参数说明：
- `webcli` - bot 别名
- `7123456789:AAH...` - 你的 bot token（从 @BotFather 获取）
- `webcli` - bot 模式（必须是 "webcli"）

注意：如果需要指定 cli_type、cli_path 或 workdir，完整命令格式为：
```
/bot_add <alias> <token> <bot_mode> [cli_type] [cli_path] [workdir]
```

### 2. 启动 webcli bot

主 bot 会自动启动 webcli bot。你也可以手动控制：

```
/bot_start webcli    # 启动
/bot_stop webcli     # 停止
/bot_list            # 查看所有 bot 状态
```

### 3. 使用 webcli bot

切换到你的 webcli bot，发送：

```
/start
```

Bot 会返回类似这样的消息：

```
🌐 Web CLI 已启动！

📱 点击下方链接访问:
https://abc123.ngrok-free.app

💡 提示: 可以在手机浏览器中打开此链接
```

### 4. 在手机浏览器中访问

点击链接，你会看到一个简单的终端界面：

```
🖥️ Web CLI Terminal

Welcome to Web CLI!
This is a simple web-based command line interface.
More features coming soon...

$ Ready for commands
```

### 5. 查看状态

```
/status
```

返回：
```
📊 Web CLI 状态

Web 服务器: 🟢 运行中
ngrok 隧道: 🟢 运行中

🌐 访问地址:
https://abc123.ngrok-free.app
```

### 6. 停止服务

```
/stop
```

## 完整命令列表

| 命令 | 说明 |
|------|------|
| `/start` | 启动 web 服务器和 ngrok，返回访问 URL |
| `/status` | 查看服务状态和访问 URL |
| `/stop` | 停止 web 服务器和 ngrok |

## 配置文件示例

`managed_bots.json`:

```json
{
  "bots": [
    {
      "alias": "webcli",
      "token": "7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
      "cli_type": "claude",
      "cli_path": "claude",
      "working_dir": "C:\\Users\\JiangKai\\telegram_cli_bridge\\refactoring",
      "enabled": true,
      "bot_mode": "webcli"
    }
  ]
}
```

## 注意事项

1. **ngrok 必须已安装并配置 authtoken**
   ```bash
   ngrok config add-authtoken YOUR_TOKEN
   ```

2. **端口 8080 不能被占用**
   - 如果被占用，需要修改代码中的端口号

3. **URL 是公开的**
   - ngrok 免费版的 URL 任何人都可以访问
   - 建议后续添加身份验证

4. **可以关闭 ngrok web 界面**
   - ngrok 启动后会打开 http://127.0.0.1:4040
   - 这个页面可以关闭，bot 通过 API 获取 URL

## 故障排查

### 问题：启动失败

**可能原因 1**: ngrok 未安装或未配置

```bash
# 检查 ngrok 是否安装
ngrok version

# 检查配置
ngrok config check
```

**可能原因 2**: 端口被占用

```bash
# Windows 查看端口占用
netstat -ano | findstr :8080

# 结束占用进程
taskkill /PID <进程ID> /F
```

### 问题：无法获取 URL

等待 3-5 秒后重试 `/status`，ngrok 需要一些时间启动。

### 问题：手机无法访问

检查：
1. URL 是否正确复制
2. 手机是否有网络连接
3. ngrok 服务是否正常运行（`/status` 查看）

## 下一步

当前版本只是一个简单的静态页面。后续可以扩展：

1. **交互式终端** - 支持输入命令并执行
2. **文件管理** - 上传/下载文件
3. **实时日志** - 查看 bot 运行日志
4. **身份验证** - 添加登录功能
5. **WebSocket** - 实时双向通信
