# Kimi Web Bot 快速使用指南

## 简介

Kimi Web Bot 是一个专门用于启动和管理 Kimi Web UI 的 Telegram 机器人。它可以自动启动 `kimi web` 命令，并通过 ngrok 将 Kimi 的 Web 界面暴露到公网，让你可以在任何设备上访问。

## 前置条件

1. **Kimi CLI 已安装**
   ```bash
   # 验证 Kimi CLI 是否可用
   kimi --version
   ```

2. **ngrok 已安装并配置**
   ```bash
   # 验证 ngrok 是否可用
   ngrok version

   # 配置 authtoken（如果还没配置）
   ngrok config add-authtoken YOUR_AUTHTOKEN
   ```

3. **Bot 已配置为 webcli 模式**

   在 `managed_bots.json` 中添加：
   ```json
   {
     "bot_id": "YOUR_BOT_TOKEN",
     "bot_mode": "webcli",
     "cli_type": "kimi",
     "working_directory": "C:\\your\\project\\path"
   }
   ```

## 使用步骤

### 1. 启动服务

在 Telegram 中向 bot 发送：
```
/start
```

Bot 会执行以下操作：
1. 在指定的工作目录启动 `kimi web`
2. 解析 Kimi 输出，获取本地 URL（如 `http://127.0.0.1:5494`）
3. 启动 ngrok 隧道，将本地 URL 转发到公网
4. 返回公网 URL

示例响应：
```
🌐 Kimi Web 已启动！

📱 点击下方链接访问 Kimi Web UI:
https://abc123.ngrok-free.app

💡 使用说明:
• 网页打开后可以直接使用 Kimi 的 Web 界面
• 支持所有 Kimi Web UI 功能
• 使用 /stop 命令停止服务
```

### 2. 访问 Kimi Web UI

点击返回的公网链接，即可在浏览器中打开 Kimi Web UI。

支持的设备：
- 手机浏览器
- 平板浏览器
- 桌面浏览器

### 3. 查看状态

发送：
```
/status
```

示例响应：
```
📊 Kimi Web 状态

Kimi Web: 🟢 运行中
ngrok 隧道: 🟢 运行中

🏠 本地地址:
http://127.0.0.1:5494

🌐 公网地址:
https://abc123.ngrok-free.app
```

### 4. 停止服务

发送：
```
/stop
```

Bot 会自动停止：
- Kimi Web 进程
- ngrok 隧道进程

## 常见问题

### Q: 启动失败，提示 "启动 Kimi Web 失败"

**可能原因：**
1. Kimi CLI 未安装或不在 PATH 中
2. 工作目录不存在或无权限
3. 端口被占用

**解决方法：**
```bash
# 1. 验证 Kimi CLI
kimi --version

# 2. 手动测试 kimi web
cd C:\your\project\path
kimi web

# 3. 检查端口占用
netstat -ano | findstr :5494
```

### Q: Kimi Web 启动成功，但 ngrok 隧道创建失败

**可能原因：**
1. ngrok 未安装或不在 PATH 中
2. ngrok authtoken 未配置
3. 网络连接问题
4. ngrok 免费版限制

**解决方法：**
```bash
# 1. 验证 ngrok
ngrok version

# 2. 配置 authtoken
ngrok config add-authtoken YOUR_AUTHTOKEN

# 3. 手动测试 ngrok
ngrok http 5494
```

### Q: 公网 URL 无法访问

**可能原因：**
1. ngrok 隧道已断开
2. Kimi Web 进程已退出
3. 防火墙阻止

**解决方法：**
1. 发送 `/status` 检查服务状态
2. 如果服务已停止，重新发送 `/start`
3. 检查防火墙设置

### Q: 如何更改工作目录？

使用管理命令（需要主 bot 权限）：
```
/bot_set_workdir <bot_id> <new_directory>
```

或直接修改 `managed_bots.json` 文件后重启 bot。

## 技术细节

### Kimi Web 启动输出

Kimi Web 启动时会输出类似以下内容：
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

Bot 会自动解析 `➜  Local` 后面的 URL。

### 端口说明

- **Kimi Web**: 默认使用 5494 端口（可能变化）
- **ngrok API**: 使用 4040 端口
- **ngrok 隧道**: 动态分配公网端口

### 进程管理

- Bot 会跟踪 Kimi Web 和 ngrok 进程的 PID
- 停止服务时会先尝试 `terminate()`，3 秒后强制 `kill()`
- 进程管理使用线程锁确保线程安全

## 安全建议

1. **不要分享公网 URL** - ngrok 生成的 URL 是公开的，任何人都可以访问
2. **及时停止服务** - 使用完毕后及时发送 `/stop` 停止服务
3. **使用 ngrok 付费版** - 免费版有连接数和时长限制，付费版更稳定
4. **定期更换 authtoken** - 如果 authtoken 泄露，及时更换

## 高级用法

### 自定义 ngrok 配置

编辑 `~/.ngrok2/ngrok.yml` 或 `~/.config/ngrok/ngrok.yml`：

```yaml
authtoken: YOUR_AUTHTOKEN
tunnels:
  kimi:
    proto: http
    addr: 5494
    # 添加自定义域名（需要付费版）
    # hostname: kimi.yourdomain.com
```

### 使用环境变量

在 `.env` 文件中设置：
```bash
NGROK_AUTHTOKEN=your_authtoken_here
NGROK_DIR=C:\path\to\ngrok
```

## 相关文档

- [KIMI_WEB_REFACTOR.md](./KIMI_WEB_REFACTOR.md) - 重构说明
- [WEBCLI_IMPLEMENTATION.md](./WEBCLI_IMPLEMENTATION.md) - 实现总结
- [CLAUDE.md](../CLAUDE.md) - 项目架构文档
