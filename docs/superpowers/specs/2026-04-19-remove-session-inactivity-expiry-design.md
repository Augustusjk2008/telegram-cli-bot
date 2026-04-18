# Remove Session Inactivity Expiry Design

日期：2026-04-19

## 目标

去掉“Bot 长时间未回复后自动重置会话”的行为。

本次只移除基于不活跃时长的自动过期逻辑，保留以下行为不变：

- 手动重置会话
- 因工作目录变更触发的会话重置
- 因 CLI 原生错误触发的会话重置
- CLI 执行超时终止

## 范围

本次包含：

- 移除 `UserSession` 基于 `last_activity` 的过期判断
- 移除 `get_session()` 获取已有会话时的“过期则重建”行为
- 移除未被调用的过期清理辅助逻辑
- 移除 `SESSION_TIMEOUT` 配置和启动日志中的“会话超时”输出
- 更新相关测试，使其锁定“会话不会因不活跃自动被替换”

本次不包含：

- 修改 `last_activity` 的记录与持久化格式
- 修改手动 `/reset` 和 Web 重置接口
- 修改工作目录切换导致的 reset 行为
- 修改 Codex / Claude 原生 session 错误检测

## 现状

当前“不活跃自动重置”由以下链路组成：

- [`bot/config.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/config.py) 定义 `SESSION_TIMEOUT`，默认值为 `3600`
- [`bot/models.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/models.py) 的 `UserSession.is_expired()` 用 `last_activity` 与 `SESSION_TIMEOUT` 比较
- [`bot/sessions.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py) 的 `get_or_create_session()` 在读取已有 session 时，如果 `is_expired()` 为真，会先把旧 session 移除并终止进程，再创建新对象
- [`bot/main.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/main.py) 启动时会打印“会话超时: <N>秒”

同时，仓库里还有 [`bot/sessions.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py) 的 `cleanup_expired_sessions()`，但当前没有调用点，因此实际用户可见的“自动重置”主要来自 `get_session()` 这条路径。

## 方案比较

### 方案 A：彻底删除不活跃过期机制

- 删除 `SESSION_TIMEOUT`
- 删除 `UserSession.is_expired()`
- `get_session()` 不再因为长时间未活动而替换会话对象
- 删除未使用的 `cleanup_expired_sessions()`

优点：

- 行为最符合需求
- 代码边界更清晰，不再保留无效配置
- 避免用户误以为系统还存在某个隐式超时开关

缺点：

- 以后如果想恢复该功能，需要重新引入配置和逻辑

### 方案 B：保留机制但默认关闭

- 保留 `SESSION_TIMEOUT`
- 约定 `0` 或负数表示禁用

优点：

- 保留配置开关

缺点：

- 行为和代码复杂度仍然存在
- 容易产生“当前到底有没有自动过期”的歧义

### 方案 C：只取消重建会话对象，保留过期概念

- `is_expired()` 仍存在
- 但不再在 `get_session()` 中使用

优点：

- 改动表面更小

缺点：

- 留下无实际用途的过期概念
- 后续维护时更难判断哪些逻辑还有效

## 已选方案

采用方案 A。

原因：

- 需求非常明确，是“去掉这个自动重置时间”，不是“把默认值调大”或“隐藏配置”。
- 当前自动重置入口集中，移除成本低。
- `last_activity` 仍可继续用于统计和状态持久化，不影响其他功能。

## 设计

### 1. 会话生命周期

`UserSession` 不再具备“不活跃即过期”的生命周期语义。

会话对象只会在以下情况下被替换或清除：

- 显式调用 reset
- 工作目录变更需要 reset
- 进程异常导致上层逻辑主动 reset
- 进程或服务重启后按现有持久化恢复逻辑重新装载

仅仅“长时间没说话”不会再导致新的 `UserSession` 被创建。

### 2. 数据字段处理

`last_activity` 字段保留。

原因：

- `touch()` 仍然会更新它，现有持久化结构无需迁移
- 已有存储文件和测试仍依赖该字段存在
- 该字段后续仍可用于展示、诊断或统计，但不再参与 reset 决策

### 3. 配置与启动输出

删除 `SESSION_TIMEOUT` 配置项及其引用。

对应地：

- `bot/config.py` 不再暴露该常量
- `bot/main.py` 不再打印“会话超时”
- `tests/test_config.py` 中与该常量存在性绑定的断言需要改写或删除

这样可以避免用户继续在 `.env` 中误以为它还会生效。

### 4. 过期清理辅助逻辑

删除未被调用的 `cleanup_expired_sessions()`。

原因：

- 它依赖同一套过期判断
- 当前无实际调用方
- 继续保留会制造“代码里还有另一条自动清理路径”的错觉

## 测试

测试需要覆盖：

- `get_session()` 在 `last_activity` 很旧时，仍返回同一个内存 session，而不是创建新对象
- `UserSession.touch()` 仍会更新 `last_activity` 和 `message_count`
- 不再依赖 `SESSION_TIMEOUT` 常量存在

受影响的测试文件：

- [`tests/test_sessions.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_sessions.py)
- [`tests/test_models.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_models.py)
- [`tests/test_config.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_config.py)

按最小范围补跑这些测试；如果实现改动波及启动导入链，再补跑相关 smoke 测试。

## 风险与处理

风险 1：删除 `SESSION_TIMEOUT` 后，用户现有 `.env` 中仍保留该项。

处理：

- 代码层忽略该项，不再读取
- 启动日志不再输出相关信息，避免继续形成误导

风险 2：测试或其他代码仍隐式依赖 `is_expired()`。

处理：

- 先用测试锁定新行为，再删除实现
- 用全文检索确认无残余调用

风险 3：长期不活动的会话对象在进程内存中停留更久。

处理：

- 当前仓库没有活跃的自动清理调用链，这一改动只会去掉“重新取会话时被替换”的行为
- 现有显式 reset、Bot 清理、进程退出仍然负责回收会话
