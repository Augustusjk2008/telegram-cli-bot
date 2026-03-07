# Telegram CLI Bridge 热加载与插件化设计方案

## 目录
1. [架构分析](#架构分析)
2. [热加载方案](#热加载方案)
3. [插件化方案](#插件化方案)
4. [实施路线图](#实施路线图)
5. [风险评估](#风险评估)

---

## 架构分析

### 当前架构特点

**核心组件**:
- `MultiBotManager`: 多Bot生命周期管理器
- `register_handlers()`: Handler注册系统（基于bot_mode动态注册）
- CLI抽象层 (`bot/cli.py`): 支持Kimi/Claude/Codex三种CLI
- Session管理 (`bot/sessions.py`): 按(bot_id, user_id)隔离的会话状态
- Handler模块 (`bot/handlers/`): 8个独立的handler文件

**可扩展点**:
1. **Handler系统**: 已经模块化，易于插件化
2. **CLI后端**: 抽象层设计良好，支持多种CLI
3. **Bot模式**: 已支持"cli"和"assistant"两种模式
4. **配置系统**: 基于环境变量+JSON文件

---

## 热加载方案

### 1. Handler热加载

**目标**: 无需重启Bot即可更新/添加/删除命令处理器

#### 1.1 设计思路

```python
# bot/hot_reload.py
import importlib
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class HandlerReloader:
    """Handler模块热加载器"""

    def __init__(self, handler_dir: Path):
        self.handler_dir = handler_dir
        self.loaded_modules: Dict[str, Any] = {}
        self.file_observer: Optional[Observer] = None

    def watch_and_reload(self):
        """监听handler目录变化并自动重载"""
        event_handler = HandlerFileEventHandler(self)
        self.file_observer = Observer()
        self.file_observer.schedule(event_handler, str(self.handler_dir), recursive=False)
        self.file_observer.start()

    def reload_handler(self, module_name: str):
        """重载指定handler模块"""
        full_name = f"bot.handlers.{module_name}"
        if full_name in sys.modules:
            importlib.reload(sys.modules[full_name])
        else:
            importlib.import_module(full_name)

    def apply_handlers(self, application: Application):
        """重新注册所有handlers"""
        # 清除现有handlers
        application.handlers.clear()
        # 重新注册
        from bot.handlers import register_handlers
        register_handlers(application, include_admin=application.bot_data.get("is_main", False))
```

#### 1.2 实施步骤

**Phase 1: 基础热加载**
- 添加 `watchdog` 依赖监听文件变化
- 实现 `HandlerReloader` 类
- 在 `MultiBotManager` 中集成热加载器
- 添加 `/reload_handlers` 管理命令

**Phase 2: 安全机制**
- 语法检查：重载前验证Python语法
- 回滚机制：重载失败时恢复旧版本
- 版本追踪：记录每次重载的时间戳和变更
- 权限控制：仅主Bot的管理员可触发重载

**Phase 3: 增强功能**
- 选择性重载：仅重载变更的模块
- 依赖分析：自动重载依赖模块
- 热重载通知：向管理员发送重载结果

#### 1.3 使用示例

```python
# 用户修改 bot/handlers/chat.py
# 系统自动检测变化并重载

# 或手动触发
/reload_handlers chat
# 输出: ✅ Handler 'chat' 已重载 (0.23s)
```

---

### 2. 配置热加载

**目标**: 动态更新配置而无需重启

#### 2.1 设计思路

```python
# bot/config_manager.py
class ConfigManager:
    """配置热加载管理器"""

    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.config: Dict[str, Any] = {}
        self.watchers: List[Callable] = []

    def load_config(self):
        """加载配置文件"""
        with open(self.config_file) as f:
            self.config = json.load(f)
        self._notify_watchers()

    def watch_config(self):
        """监听配置文件变化"""
        # 使用watchdog监听

    def register_watcher(self, callback: Callable):
        """注册配置变更回调"""
        self.watchers.append(callback)

    def get(self, key: str, default=None):
        """获取配置值"""
        return self.config.get(key, default)
```

#### 2.2 可热加载的配置项

**安全可热加载**:
- `CLI_EXEC_TIMEOUT`: CLI执行超时
- `SESSION_TIMEOUT`: 会话超时
- `CLI_PROGRESS_UPDATE_INTERVAL`: 进度更新间隔
- `WHISPER_MODEL`: Whisper模型
- `ANTHROPIC_MODEL`: Claude模型
- `ALLOWED_USER_IDS`: 授权用户列表（需谨慎）

**需要重启**:
- `TELEGRAM_BOT_TOKEN`: Bot Token
- `PROXY_URL`: 代理配置
- `WORKING_DIR`: 工作目录（影响会话状态）

#### 2.3 实施步骤

1. 创建 `ConfigManager` 类
2. 将环境变量配置迁移到JSON配置文件
3. 实现配置文件监听
4. 添加 `/reload_config` 命令
5. 为关键组件添加配置变更回调

---

### 3. CLI后端热加载

**目标**: 动态添加新的CLI后端支持

#### 3.1 设计思路

```python
# bot/cli_registry.py
class CLIBackend:
    """CLI后端抽象基类"""

    @property
    def name(self) -> str:
        """CLI类型名称"""
        raise NotImplementedError

    def build_command(self, user_text: str, session_id: Optional[str], **kwargs) -> Tuple[List[str], bool]:
        """构建CLI命令"""
        raise NotImplementedError

    def parse_output(self, raw_output: str) -> Tuple[str, Optional[str]]:
        """解析CLI输出"""
        raise NotImplementedError

    def should_reset_session(self, response: str, returncode: int) -> bool:
        """判断是否需要重置会话"""
        return False

class CLIRegistry:
    """CLI后端注册表"""

    def __init__(self):
        self.backends: Dict[str, CLIBackend] = {}

    def register(self, backend: CLIBackend):
        """注册CLI后端"""
        self.backends[backend.name] = backend

    def get(self, name: str) -> Optional[CLIBackend]:
        """获取CLI后端"""
        return self.backends.get(name)

    def load_from_directory(self, plugin_dir: Path):
        """从目录加载CLI插件"""
        for file in plugin_dir.glob("cli_*.py"):
            module = importlib.import_module(f"plugins.{file.stem}")
            if hasattr(module, "register_backend"):
                backend = module.register_backend()
                self.register(backend)
```

#### 3.2 插件示例

```python
# plugins/cli_aider.py
from bot.cli_registry import CLIBackend

class AiderBackend(CLIBackend):
    @property
    def name(self) -> str:
        return "aider"

    def build_command(self, user_text: str, session_id: Optional[str], **kwargs):
        cmd = ["aider", "--yes", "--no-auto-commits"]
        if session_id:
            cmd.extend(["--chat-history-file", f".aider.{session_id}.txt"])
        cmd.extend(["--message", user_text])
        return cmd, False

    def parse_output(self, raw_output: str):
        return raw_output.strip(), None

def register_backend():
    return AiderBackend()
```

#### 3.3 实施步骤

1. 重构 `bot/cli.py` 为基于注册表的架构
2. 创建 `CLIBackend` 抽象基类
3. 将现有Kimi/Claude/Codex迁移为插件
4. 实现插件目录扫描和加载
5. 添加 `/cli_list` 和 `/cli_reload` 命令

---

## 插件化方案

### 1. Handler插件系统

**目标**: 第三方可以开发独立的Handler插件

#### 1.1 插件结构

```
plugins/
├── __init__.py
├── weather/                    # 天气查询插件
│   ├── __init__.py
│   ├── plugin.json            # 插件元数据
│   ├── handlers.py            # Handler实现
│   └── requirements.txt       # 依赖
├── translator/                # 翻译插件
│   ├── __init__.py
│   ├── plugin.json
│   └── handlers.py
└── github_integration/        # GitHub集成插件
    ├── __init__.py
    ├── plugin.json
    ├── handlers.py
    └── config.json
```

#### 1.2 插件元数据

```json
// plugins/weather/plugin.json
{
  "name": "weather",
  "version": "1.0.0",
  "description": "天气查询插件",
  "author": "Your Name",
  "bot_modes": ["cli", "assistant"],  // 支持的Bot模式
  "commands": [
    {
      "command": "weather",
      "description": "查询天气",
      "usage": "/weather <城市名>"
    }
  ],
  "dependencies": ["requests"],
  "config_schema": {
    "api_key": {"type": "string", "required": true}
  }
}
```

#### 1.3 插件API

```python
# bot/plugin_system.py
class PluginBase:
    """插件基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def get_handlers(self) -> List[Tuple[str, Callable]]:
        """返回 [(command_name, handler_function), ...]"""
        raise NotImplementedError

    def on_load(self):
        """插件加载时调用"""
        pass

    def on_unload(self):
        """插件卸载时调用"""
        pass

    def on_config_change(self, new_config: Dict[str, Any]):
        """配置变更时调用"""
        self.config = new_config

class PluginManager:
    """插件管理器"""

    def __init__(self, plugin_dir: Path):
        self.plugin_dir = plugin_dir
        self.plugins: Dict[str, PluginBase] = {}

    def load_plugin(self, plugin_name: str):
        """加载插件"""
        plugin_path = self.plugin_dir / plugin_name
        metadata = self._load_metadata(plugin_path / "plugin.json")

        # 检查依赖
        self._check_dependencies(metadata)

        # 加载插件模块
        module = importlib.import_module(f"plugins.{plugin_name}.handlers")
        plugin_class = getattr(module, "Plugin")

        # 加载配置
        config = self._load_plugin_config(plugin_name)

        # 实例化插件
        plugin = plugin_class(config)
        plugin.on_load()

        self.plugins[plugin_name] = plugin

    def unload_plugin(self, plugin_name: str):
        """卸载插件"""
        if plugin_name in self.plugins:
            self.plugins[plugin_name].on_unload()
            del self.plugins[plugin_name]

    def register_plugin_handlers(self, application: Application):
        """注册所有插件的handlers"""
        bot_mode = application.bot_data.get("bot_mode", "cli")

        for plugin_name, plugin in self.plugins.items():
            metadata = self._get_metadata(plugin_name)

            # 检查插件是否支持当前Bot模式
            if bot_mode not in metadata.get("bot_modes", ["cli", "assistant"]):
                continue

            # 注册handlers
            for cmd, handler in plugin.get_handlers():
                application.add_handler(CommandHandler(cmd, handler))
```

#### 1.4 插件示例

```python
# plugins/weather/handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from bot.plugin_system import PluginBase
import requests

class Plugin(PluginBase):
    def get_handlers(self):
        return [
            ("weather", self.handle_weather),
            ("forecast", self.handle_forecast),
        ]

    async def handle_weather(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理天气查询"""
        if not context.args:
            await update.message.reply_text("用法: /weather <城市名>")
            return

        city = " ".join(context.args)
        api_key = self.config.get("api_key")

        # 调用天气API
        response = requests.get(
            f"https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": api_key, "lang": "zh_cn"}
        )

        if response.status_code == 200:
            data = response.json()
            weather = data["weather"][0]["description"]
            temp = data["main"]["temp"] - 273.15
            await update.message.reply_text(
                f"🌤 {city} 天气\n"
                f"状况: {weather}\n"
                f"温度: {temp:.1f}°C"
            )
        else:
            await update.message.reply_text("❌ 查询失败，请检查城市名")
```

---

### 2. 中间件系统

**目标**: 支持消息处理管道的插件化

#### 2.1 设计思路

```python
# bot/middleware.py
class Middleware:
    """中间件基类"""

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, next_handler):
        """处理消息，调用next_handler继续管道"""
        return await next_handler(update, context)

class MiddlewareChain:
    """中间件链"""

    def __init__(self):
        self.middlewares: List[Middleware] = []

    def use(self, middleware: Middleware):
        """添加中间件"""
        self.middlewares.append(middleware)

    async def execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, final_handler):
        """执行中间件链"""
        index = 0

        async def next_handler(update, context):
            nonlocal index
            if index < len(self.middlewares):
                middleware = self.middlewares[index]
                index += 1
                return await middleware.process_message(update, context, next_handler)
            else:
                return await final_handler(update, context)

        return await next_handler(update, context)
```

#### 2.2 中间件示例

```python
# plugins/rate_limiter/middleware.py
from bot.middleware import Middleware
from collections import defaultdict
from datetime import datetime, timedelta

class RateLimiterMiddleware(Middleware):
    """速率限制中间件"""

    def __init__(self, max_requests: int = 10, window: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window)
        self.requests = defaultdict(list)

    async def process_message(self, update, context, next_handler):
        user_id = update.effective_user.id
        now = datetime.now()

        # 清理过期记录
        self.requests[user_id] = [
            t for t in self.requests[user_id]
            if now - t < self.window
        ]

        # 检查速率限制
        if len(self.requests[user_id]) >= self.max_requests:
            await update.message.reply_text(
                f"⚠️ 请求过于频繁，请{self.window.seconds}秒后再试"
            )
            return

        self.requests[user_id].append(now)
        return await next_handler(update, context)

# plugins/logger/middleware.py
class LoggerMiddleware(Middleware):
    """日志记录中间件"""

    async def process_message(self, update, context, next_handler):
        user_id = update.effective_user.id
        text = update.message.text
        logger.info(f"User {user_id}: {text}")

        result = await next_handler(update, context)

        logger.info(f"Response sent to {user_id}")
        return result
```

---

### 3. 事件系统

**目标**: 支持事件驱动的插件通信

#### 3.1 设计思路

```python
# bot/event_bus.py
class EventBus:
    """事件总线"""

    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event_name: str, callback: Callable):
        """注册事件监听器"""
        self.listeners[event_name].append(callback)

    def off(self, event_name: str, callback: Callable):
        """移除事件监听器"""
        if callback in self.listeners[event_name]:
            self.listeners[event_name].remove(callback)

    async def emit(self, event_name: str, *args, **kwargs):
        """触发事件"""
        for callback in self.listeners[event_name]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args, **kwargs)
                else:
                    callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"事件处理器错误 {event_name}: {e}")
```

#### 3.2 内置事件

```python
# 系统事件
"bot.started"           # Bot启动
"bot.stopped"           # Bot停止
"bot.restarted"         # Bot重启
"session.created"       # 会话创建
"session.expired"       # 会话过期
"session.reset"         # 会话重置

# 消息事件
"message.received"      # 收到消息
"message.sent"          # 发送消息
"command.executed"      # 命令执行
"cli.started"           # CLI进程启动
"cli.completed"         # CLI进程完成
"cli.error"             # CLI执行错误

# 插件事件
"plugin.loaded"         # 插件加载
"plugin.unloaded"       # 插件卸载
"config.changed"        # 配置变更
```

#### 3.3 使用示例

```python
# plugins/analytics/handlers.py
class Plugin(PluginBase):
    def on_load(self):
        event_bus.on("message.received", self.track_message)
        event_bus.on("command.executed", self.track_command)

    def on_unload(self):
        event_bus.off("message.received", self.track_message)
        event_bus.off("command.executed", self.track_command)

    async def track_message(self, update: Update):
        # 记录消息统计
        pass

    async def track_command(self, command: str, user_id: int):
        # 记录命令统计
        pass
```

---

## 实施路线图

### Phase 1: 基础热加载 (1-2周)

**目标**: 实现Handler和配置的基础热加载

- [ ] 添加 `watchdog` 依赖
- [ ] 实现 `HandlerReloader` 类
- [ ] 实现 `ConfigManager` 类
- [ ] 在 `MultiBotManager` 中集成热加载器
- [ ] 添加 `/reload_handlers` 和 `/reload_config` 命令
- [ ] 编写单元测试

**交付物**:
- `bot/hot_reload.py`
- `bot/config_manager.py`
- 更新的 `bot/manager.py`
- 测试用例

### Phase 2: CLI插件化 (2-3周)

**目标**: 将CLI后端改造为插件系统

- [ ] 设计 `CLIBackend` 抽象基类
- [ ] 创建 `CLIRegistry` 注册表
- [ ] 重构现有Kimi/Claude/Codex为插件
- [ ] 实现插件目录扫描和加载
- [ ] 添加CLI插件管理命令
- [ ] 编写插件开发文档

**交付物**:
- `bot/cli_registry.py`
- `plugins/cli_kimi.py`
- `plugins/cli_claude.py`
- `plugins/cli_codex.py`
- `docs/CLI_PLUGIN_DEVELOPMENT.md`

### Phase 3: Handler插件系统 (2-3周)

**目标**: 实现完整的Handler插件系统

- [ ] 设计 `PluginBase` 抽象基类
- [ ] 实现 `PluginManager` 插件管理器
- [ ] 实现插件元数据解析
- [ ] 实现插件依赖检查
- [ ] 实现插件配置管理
- [ ] 添加插件管理命令 (`/plugin_list`, `/plugin_load`, `/plugin_unload`)
- [ ] 开发示例插件（天气、翻译）
- [ ] 编写插件开发文档

**交付物**:
- `bot/plugin_system.py`
- `plugins/weather/`
- `plugins/translator/`
- `docs/PLUGIN_DEVELOPMENT_GUIDE.md`

### Phase 4: 中间件和事件系统 (1-2周)

**目标**: 实现中间件和事件总线

- [ ] 实现 `Middleware` 基类和 `MiddlewareChain`
- [ ] 实现 `EventBus` 事件总线
- [ ] 在关键位置触发事件
- [ ] 开发示例中间件（速率限制、日志）
- [ ] 编写中间件开发文档

**交付物**:
- `bot/middleware.py`
- `bot/event_bus.py`
- `plugins/rate_limiter/`
- `plugins/logger/`
- `docs/MIDDLEWARE_GUIDE.md`

### Phase 5: 安全和稳定性 (1-2周)

**目标**: 增强系统的安全性和稳定性

- [ ] 实现插件沙箱（资源限制）
- [ ] 实现热加载回滚机制
- [ ] 实现插件签名验证
- [ ] 添加插件权限系统
- [ ] 性能优化和压力测试
- [ ] 完善错误处理和日志

**交付物**:
- `bot/plugin_sandbox.py`
- `bot/plugin_security.py`
- 性能测试报告
- 安全审计报告

### Phase 6: 文档和生态 (持续)

**目标**: 建立插件生态系统

- [ ] 完善所有开发文档
- [ ] 创建插件市场/仓库
- [ ] 编写最佳实践指南
- [ ] 提供插件模板和脚手架
- [ ] 建立社区贡献流程

**交付物**:
- 完整的开发者文档
- 插件模板仓库
- 社区贡献指南

---

## 风险评估

### 技术风险

**1. 热加载稳定性**
- **风险**: 模块重载可能导致内存泄漏或状态不一致
- **缓解**:
  - 实现严格的模块卸载流程
  - 添加内存监控和泄漏检测
  - 提供回滚机制

**2. 插件安全性**
- **风险**: 恶意插件可能危害系统安全
- **缓解**:
  - 实现插件沙箱和权限系统
  - 代码审查和签名验证
  - 资源使用限制

**3. 性能影响**
- **风险**: 插件系统可能增加延迟
- **缓解**:
  - 异步加载和懒加载
  - 插件性能监控
  - 缓存和优化

### 兼容性风险

**1. 现有功能破坏**
- **风险**: 重构可能破坏现有功能
- **缓解**:
  - 渐进式迁移
  - 完整的测试覆盖
  - 保持向后兼容

**2. 依赖冲突**
- **风险**: 插件依赖可能冲突
- **缓解**:
  - 依赖隔离（虚拟环境）
  - 版本锁定
  - 依赖检查工具

### 维护风险

**1. 复杂度增加**
- **风险**: 系统复杂度显著提升
- **缓解**:
  - 清晰的架构文档
  - 代码注释和示例
  - 开发者培训

**2. 生态碎片化**
- **风险**: 插件质量参差不齐
- **缓解**:
  - 官方插件认证
  - 质量评分系统
  - 社区审查机制

---

## 总结

### 优先级建议

**高优先级** (立即实施):
1. Handler热加载 - 提升开发效率
2. 配置热加载 - 减少重启次数
3. CLI插件化 - 扩展CLI支持

**中优先级** (3个月内):
4. Handler插件系统 - 支持功能扩展
5. 事件系统 - 解耦组件通信

**低优先级** (长期规划):
6. 中间件系统 - 高级功能
7. 插件市场 - 生态建设

### 预期收益

1. **开发效率**: 热加载减少50%+的重启时间
2. **可扩展性**: 插件系统支持无限功能扩展
3. **维护性**: 模块化降低维护成本
4. **社区**: 开放生态吸引贡献者

### 下一步行动

1. 评审本方案并确定优先级
2. 创建详细的技术设计文档
3. 搭建开发分支和测试环境
4. 开始Phase 1实施
