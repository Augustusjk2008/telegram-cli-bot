# Web CLI Bot 实现总结

## 实现内容

### 1. 新增文件

- `bot/handlers/webcli.py` - Web CLI 模式处理器
- `docs/WEBCLI_QUICKSTART.md` - 快速开始指南
- `docs/WEBCLI_USAGE.md` - 详细使用说明
- `test_webcli.py` - 配置辅助脚本

### 2. 修改文件

- `bot/handlers/__init__.py` - 添加 webcli 模式的 handler 注册
- `bot/manager.py` - 支持 "webcli" bot_mode
- `bot/models.py` - BotProfile 已支持 bot_mode 字段（无需修改）

## 功能特性

### 核心功能

1. **启动 Web 服务器**
   - 使用 Python 内置的 `http.server`
   - 默认端口 8080
   - 提供简单的 HTML 终端界面

2. **ngrok 隧道**
   - 自动启动 ngrok
   - 通过 ngrok API 获取公网 URL
   - 支持状态查询

3. **Telegram 集成**
   - `/start` - 启动服务并返回 URL
   - `/status` - 查看服务状态
   - `/stop` - 停止服务

### 技术实现

```python
# 架构流程
Telegram Bot (webcli mode)
    ↓
Python HTTP Server (port 8080)
    ↓
ngrok tunnel
    ↓
Public URL (https://xxx.ngrok-free.app)
    ↓
Mobile Browser
```

### 关键代码

**启动 Web 服务器**:
```python
subprocess.Popen(
    ["python", "-m", "http.server", str(port), "--directory", str(html_dir)],
    ...
)
```

**启动 ngrok**:
```python
subprocess.Popen(
    ["ngrok", "http", str(port), "--log=stdout"],
    ...
)
```

**获取 ngrok URL**:
```python
with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as response:
    data = json.loads(response.read())
    url = data["tunnels"][0]["public_url"]
```

## 使用方法

### 添加 webcli bot

方法 1 - 通过主 bot:
```
/bot_add webcli YOUR_BOT_TOKEN webcli
```

方法 2 - 编辑 `managed_bots.json`:
```json
{
  "bots": [
    {
      "alias": "webcli",
      "token": "YOUR_BOT_TOKEN",
      "bot_mode": "webcli",
      ...
    }
  ]
}
```

### 使用 webcli bot

1. 发送 `/start` 启动服务
2. 点击返回的 URL 在浏览器中访问
3. 发送 `/status` 查看状态
4. 发送 `/stop` 停止服务

## 当前限制

1. **静态页面** - 目前只是一个简单的欢迎页面，没有交互功能
2. **无身份验证** - URL 是公开的，任何人都可以访问
3. **单实例** - 全局共享 web 服务器和 ngrok 进程
4. **固定端口** - 硬编码为 8080

## 后续扩展方向

### Phase 1: 交互式终端
- 添加命令输入框
- 支持执行 shell 命令
- 显示命令输出

### Phase 2: 文件管理
- 文件上传/下载
- 文件浏览器
- 文件编辑器

### Phase 3: 实时通信
- WebSocket 支持
- 实时日志流
- 双向消息推送

### Phase 4: 安全增强
- 用户身份验证
- Token 验证
- HTTPS 支持

### Phase 5: 多用户支持
- 每个用户独立的 web 实例
- 会话隔离
- 资源限制

## 依赖要求

### 必需
- Python 3.7+
- ngrok (已安装并配置 authtoken)
- Telegram Bot Token

### 可选
- 无

## 测试验证

```bash
# 测试导入
python -c "from bot.handlers.webcli import handle_webcli_start; print('OK')"

# 启动 bot
python -m bot

# 在 Telegram 中测试
/bot_add webcli YOUR_TOKEN webcli
# 切换到 webcli bot
/start
```

## 注意事项

1. **ngrok 配置**
   ```bash
   ngrok config add-authtoken YOUR_TOKEN
   ```

2. **端口占用**
   - 确保 8080 端口未被占用
   - 或修改代码中的端口号

3. **安全性**
   - 当前版本 URL 是公开的
   - 建议在生产环境添加身份验证

4. **ngrok 限制**
   - 免费版有连接数限制
   - URL 会在重启后改变

## 文件结构

```
bot/
├── handlers/
│   ├── __init__.py          # 添加 webcli handler 注册
│   └── webcli.py            # Web CLI 处理器（新增）
├── data/
│   └── webcli/
│       └── index.html       # Web 界面（自动生成）
├── manager.py               # 支持 webcli mode
└── models.py                # BotProfile 支持 bot_mode

docs/
├── WEBCLI_QUICKSTART.md     # 快速开始（新增）
└── WEBCLI_USAGE.md          # 使用说明（新增）

test_webcli.py               # 配置辅助脚本（新增）
```

## 总结

已成功实现 Web CLI bot 类型，支持：
- ✅ 启动本地 web 服务器
- ✅ 通过 ngrok 暴露到公网
- ✅ 发送 URL 给 Telegram 用户
- ✅ 在手机浏览器中访问简单页面
- ✅ 完整的生命周期管理（启动/停止/状态查询）

下一步可以根据需求扩展交互功能。
