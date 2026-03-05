# 飞书机器人集成设计方案

## 概述

本文档描述为 Telegram CLI Bridge 项目添加飞书（个人版）机器人支持的技术方案。

**目标**：在保持现有 Telegram 功能的基础上，支持飞书平台的机器人接入，实现多平台统一管理。

**工作量评估**：中等（3-5天完整实现，1-2天 MVP）

---

## 1. 架构调整

### 1.1 当前架构问题

- 代码与 Telegram SDK 强耦合（`telegram.ext.Application`、`telegram.Update`）
- `MultiBotManager` 直接依赖 Telegram 特定类型
- 消息处理逻辑混合了平台特定代码

### 1.2 目标架构

引入平台抽象层，支持多平台扩展：

```
bot/
├── platforms/
│   ├── base.py              # 平台抽象接口
│   ├── telegram/
│   │   ├── client.py        # Telegram 客户端封装
│   │   ├── handlers.py      # Telegram 处理器
│   │   └── adapter.py       # 适配到统一接口
│   └── feishu/
│       ├── client.py        # 飞书客户端封装
│       ├── handlers.py      # 飞书事件处理
│       └── adapter.py       # 适配到统一接口
├── manager.py               # 多平台 Bot 管理器（改造）
├── cli.py                   # CLI 抽象层（无需改动）
└── sessions.py              # 会话管理（需调整键结构）
```

### 1.3 核心抽象接口

```python
# bot/platforms/base.py
class BasePlatform(ABC):
    @abstractmethod
    async def start(self):
        """启动平台客户端"""

    @abstractmethod
    async def stop(self):
        """停止平台客户端"""

    @abstractmethod
    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送文本消息"""

    @abstractmethod
    async def send_file(self, chat_id: str, file_path: str, **kwargs):
        """发送文件"""

    @abstractmethod
    async def edit_message(self, chat_id: str, message_id: str, text: str):
        """编辑消息"""

class BaseMessage:
    platform: str
    chat_id: str
    user_id: str
    text: str
    files: List[str]
```

---

## 2. 飞书 SDK 集成

### 2.1 依赖安装

```bash
pip install lark-oapi  # 飞书官方 Python SDK
```

### 2.2 飞书认证配置

飞书机器人需要以下凭证（与 Telegram token 不同）：

- `app_id`: 应用 ID
- `app_secret`: 应用密钥
- `verification_token`: 事件订阅验证 token
- `encrypt_key`: 消息加密密钥（可选）

### 2.3 事件订阅模式

**关键差异**：
- Telegram: 长轮询（polling），主动拉取消息
- 飞书: Webhook 回调，被动接收事件

**实现方案**：
- 使用 `aiohttp` 启动 HTTP 服务器监听飞书回调
- 端口可配置（默认 8080）
- 需要公网可访问地址（开发环境可用 ngrok）

---

## 3. 配置文件调整

### 3.1 环境变量（.env）

新增飞书相关配置：

```bash
# 飞书 Webhook 服务器配置
FEISHU_WEBHOOK_PORT=8080
FEISHU_WEBHOOK_HOST=0.0.0.0
FEISHU_PUBLIC_URL=https://your-domain.com  # 或 ngrok URL
```

### 3.2 托管 Bot 配置（managed_bots.json）

扩展支持平台字段：

```json
{
  "bots": [
    {
      "alias": "telegram-bot-1",
      "platform": "telegram",
      "token": "123456:ABC...",
      "cli_type": "claude",
      "cli_path": "claude",
      "working_dir": "/path/to/work",
      "enabled": true
    },
    {
      "alias": "feishu-bot-1",
      "platform": "feishu",
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "verification_token": "xxx",
      "encrypt_key": "xxx",
      "cli_type": "kimi",
      "cli_path": "kimi",
      "working_dir": "/path/to/work",
      "enabled": true
    }
  ]
}
```

---

## 4. 核心模块改造

### 4.1 MultiBotManager 改造

**变更点**：

1. 支持混合平台管理
2. 根据 `platform` 字段实例化不同客户端
3. 统一生命周期管理接口

```python
class MultiBotManager:
    def __init__(self, main_profile: BotProfile, storage_file: str):
        self.platforms: Dict[str, BasePlatform] = {}  # 新增
        self.applications: Dict[str, Application] = {}  # 保留兼容

    async def _start_profile(self, profile: BotProfile, is_main: bool):
        if profile.platform == "telegram":
            return await self._start_telegram(profile, is_main)
        elif profile.platform == "feishu":
            return await self._start_feishu(profile, is_main)
```

### 4.2 会话管理调整

**当前键结构**：`(bot_id, user_id)`

**新键结构**：`(platform, bot_id, user_id)`

```python
# bot/sessions.py
def get_session(platform: str, bot_id: int, user_id: int) -> UserSession:
    key = (platform, bot_id, user_id)
    # ...
```

### 4.3 消息处理流程

统一消息处理流程：

```
飞书事件 → FeishuAdapter.parse_event()
         → 统一 Message 对象
         → 现有 CLI 处理逻辑（bot/cli.py）
         → 统一 Response 对象
         → FeishuAdapter.format_response()
         → 飞书消息卡片
```

---

## 5. 消息格式适配

### 5.1 文本格式转换

| Telegram HTML | 飞书富文本 |
|--------------|----------|
| `<b>粗体</b>` | `**粗体**` |
| `<code>代码</code>` | `` `代码` `` |
| `<pre>代码块</pre>` | ` ```代码块``` ` |

### 5.2 长文本分块

- Telegram: 4096 字符限制
- 飞书: 10000 字符限制

需要调整 `split_text_into_chunks()` 函数支持平台参数。

### 5.3 文件处理

**飞书文件上传流程**：
1. 调用上传接口获取 `file_key`
2. 使用 `file_key` 发送文件消息

**飞书文件下载流程**：
1. 从消息中提取 `file_key`
2. 调用下载接口获取临时 URL
3. 下载文件内容

---

## 6. 部署方案

### 6.1 开发环境

使用 ngrok 做内网穿透：

```bash
# 启动 ngrok
ngrok http 8080

# 将生成的 URL 配置到飞书后台
# 例如：https://abc123.ngrok.io/feishu/webhook
```

### 6.2 生产环境

**方案 A：单服务器部署**
- 需要公网 IP + 域名
- 配置 Nginx 反向代理
- HTTPS 证书（飞书要求）

**方案 B：云函数部署**
- 将飞书 Webhook 部署到云函数（腾讯云、阿里云）
- 通过消息队列与主服务通信

### 6.3 进程管理

```python
# bot/main.py
async def run_all_bots():
    manager = MultiBotManager(...)

    # 启动 Telegram polling（异步任务）
    telegram_task = asyncio.create_task(manager.start_telegram_polling())

    # 启动飞书 Webhook 服务器（阻塞）
    if manager.has_feishu_bots():
        await manager.start_feishu_webhook(port=8080)
```

---

## 7. 技术难点与解决方案

### 7.1 事件模型差异

**问题**：Telegram polling 和飞书 webhook 需要同时运行

**解决方案**：
- Telegram polling 作为后台任务（`asyncio.create_task`）
- 飞书 webhook 作为主事件循环（`aiohttp.web.run_app`）

### 7.2 消息格式转换

**问题**：Telegram HTML 与飞书富文本语法不兼容

**解决方案**：
- 创建 `MessageFormatter` 类处理格式转换
- 支持双向转换（发送和接收）

### 7.3 文件处理差异

**问题**：飞书文件需要两步操作（上传获取 key + 发送消息）

**解决方案**：
- 在 `FeishuAdapter` 中封装文件操作
- 对外提供统一的 `send_file()` 接口

### 7.4 会话隔离

**问题**：跨平台用户 ID 可能冲突

**解决方案**：
- 会话键增加 `platform` 前缀
- 确保 `(telegram, 123, 456)` 和 `(feishu, 123, 456)` 独立

---

## 8. 实施步骤

### Phase 1: 架构重构（1天）
- [ ] 创建 `bot/platforms/base.py` 抽象接口
- [ ] 将现有 Telegram 代码迁移到 `bot/platforms/telegram/`
- [ ] 调整 `MultiBotManager` 支持平台参数
- [ ] 修改会话键结构

### Phase 2: 飞书集成（1天）
- [ ] 安装 `lark-oapi` SDK
- [ ] 实现 `bot/platforms/feishu/client.py`
- [ ] 实现 `bot/platforms/feishu/handlers.py`
- [ ] 实现 `bot/platforms/feishu/adapter.py`

### Phase 3: 消息适配（1天）
- [ ] 实现消息格式转换器
- [ ] 适配文本消息处理
- [ ] 适配文件上传/下载
- [ ] 适配命令解析

### Phase 4: Webhook 服务器（1天）
- [ ] 使用 `aiohttp` 实现 HTTP 服务器
- [ ] 处理飞书事件回调
- [ ] 实现事件验证和解密
- [ ] 集成到主进程

### Phase 5: 测试与调试（0.5天）
- [ ] 单元测试适配
- [ ] 端到端测试
- [ ] 错误处理完善

### Phase 6: 文档与部署（0.5天）
- [ ] 更新 README
- [ ] 编写部署文档
- [ ] 配置示例

---

## 9. MVP 方案（快速验证）

如果只是快速验证可行性，可以先实现最小功能集：

**包含功能**：
- 单个飞书机器人支持（不支持多 bot 管理）
- 仅支持文本消息（不支持文件）
- 使用 ngrok 做内网穿透
- 复用现有 CLI 逻辑

**不包含功能**：
- 多飞书 bot 管理
- 文件上传/下载
- 消息编辑
- 富文本格式转换

**MVP 工作量**：1-2天

---

## 10. 风险与注意事项

### 10.1 技术风险

- 飞书 API 限流（需要实现重试机制）
- Webhook 稳定性（需要监控和自动恢复）
- 消息格式兼容性（部分格式可能无法完美转换）

### 10.2 运维风险

- 需要公网地址（增加部署复杂度）
- HTTPS 证书管理
- 防火墙配置

### 10.3 兼容性风险

- 现有 Telegram 功能不能受影响
- 配置文件需要向后兼容
- 数据库/会话存储需要迁移

---

## 11. 后续优化方向

1. **统一配置管理**：支持从数据库加载配置
2. **消息队列**：解耦 Webhook 接收和消息处理
3. **监控告警**：集成 Prometheus + Grafana
4. **多实例部署**：支持负载均衡
5. **更多平台**：钉钉、企业微信等

---

## 12. 参考资料

- [飞书开放平台文档](https://open.feishu.cn/document/home/index)
- [lark-oapi Python SDK](https://github.com/larksuite/oapi-sdk-python)
- [Telegram Bot API](https://core.telegram.org/bots/api)

---

**文档版本**：v1.0
**创建日期**：2026-03-05
**作者**：Claude
**状态**：设计阶段
