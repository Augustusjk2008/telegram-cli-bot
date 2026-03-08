# Web 前端任务书

## 1. 项目背景

现有项目已经有稳定的后端能力，包括：

- 多 Bot / 多 Profile 管理
- CLI 对话能力（Kimi / Claude / Codex）
- Shell 执行
- 工作目录切换与文件收发
- Assistant 模式与长期记忆
- 管理脚本执行与 Bot 管理

当前用户入口主要是 Telegram。现在要新增一个 Web 前端，使项目可以作为标准 Web 项目使用。

原则只有一条：**后端业务能力不变，Web 只是替换访问方式与交互界面。**

## 2. 本次前端目标

前端要完成一个单页 Web 应用，覆盖当前 Telegram 常用核心能力：

- 登录接入后端 Web API
- 选择 Bot/Profile
- 发送聊天消息并查看回复
- 查看/切换工作目录
- 浏览、上传、预览、下载文件
- 查看会话历史
- 在 Assistant 模式下管理长期记忆
- 在主控台查看 Bot 列表与基本状态

## 3. 范围定义

### P0 必做

- 登录页
- Bot 列表/入口页
- 主工作台
- 聊天区
- 文件区
- 会话区
- 基础状态提示与错误提示

### P1 必做

- Assistant 记忆管理页
- 管理页（Bot 启停、工作目录、CLI 配置）
- 系统脚本页

### 本期不做

- 前端直接嵌入终端模拟器
- 音频上传/语音识别
- 完整的流式 token 渲染
- 多组织、多角色权限系统
- 复杂富文本编辑器

## 4. 用户角色

### 普通使用者

- 选择某个 Bot
- 对话
- 看历史
- 管理当前工作目录与文件

### 管理者

- 查看所有 Bot 状态
- 添加/删除/启停 Bot
- 修改 CLI 配置与工作目录
- 执行系统脚本
- 触发后端重启

当前版本可默认按“所有已授权用户均可进入管理页”设计，不做复杂 RBAC。

## 5. 信息架构

前端信息结构建议如下：

1. 登录页
2. Bot 选择页
3. 工作台页
4. 记忆管理页
5. 管理中心页

## 6. 页面要求

### 6.1 登录页

目标：

- 让用户输入后端地址
- 输入 API Token
- 输入或选择 User ID
- 完成 `/api/auth/me` 校验

要求：

- 首次进入必须校验连接
- 校验成功后将配置保存在本地
- 若校验失败，必须展示明确的后端错误信息

### 6.2 Bot 选择页

数据来源：`GET /api/bots`

要求：

- 列出所有 Bot/Profile
- 每个卡片展示：
  - alias
  - bot_mode
  - cli_type
  - working_dir
  - status
  - capabilities
- 点击某个 Bot 进入工作台

交互要求：

- `bot_mode=cli` 和 `bot_mode=assistant` 可以进入完整工作台
- `bot_mode=webcli` 仅显示“当前前端暂不支持该模式”的禁用提示

### 6.3 工作台页

工作台采用三栏布局，移动端改为分段折叠布局。

左栏：

- Bot 基本信息
- 当前工作目录
- 快捷操作按钮

中栏：

- 聊天区
- 输入框
- 发送按钮
- 停止当前任务按钮

右栏：

- 文件区
- 会话历史区

### 6.4 聊天区

数据接口：

- `POST /api/bots/{alias}/chat`
- `GET /api/bots/{alias}/history`
- `POST /api/bots/{alias}/reset`
- `POST /api/bots/{alias}/kill`

要求：

- 发送消息后显示“处理中”状态
- 请求完成后渲染整段回复
- 支持普通文本输入
- 支持保留 `//` 前缀语义
- 历史消息至少展示最近 50 条
- 必须有“重置会话”“终止任务”入口

交互要求：

- 输入区支持 `Enter` 发送，`Shift+Enter` 换行
- 错误态要区分：
  - 401/403 鉴权错误
  - 409 会话忙
  - 400 参数错误
  - 500 后端异常

### 6.5 Shell/目录区

数据接口：

- `POST /api/bots/{alias}/exec`
- `GET /api/bots/{alias}/pwd`
- `GET /api/bots/{alias}/ls`
- `POST /api/bots/{alias}/cd`

要求：

- 提供独立的 Shell 命令输入框
- 支持显示执行输出和返回状态
- 当前目录必须始终可见
- 目录列表需要支持点击文件夹进入
- 目录切换后需要自动刷新目录内容

### 6.6 文件区

数据接口：

- `POST /api/bots/{alias}/files/upload`
- `GET /api/bots/{alias}/files/download`
- `GET /api/bots/{alias}/files/read`

要求：

- 支持拖拽上传与按钮上传
- 支持文本文件预览
- 支持下载
- 支持 `head` 与 `cat` 两种查看模式

限制提示：

- 上传大小限制 20MB
- 大文本文件提示改用下载

### 6.7 Assistant 记忆页

数据接口：

- `GET /api/memory`
- `POST /api/memory`
- `GET /api/memory/search`
- `DELETE /api/memory/{memory_id}`
- `DELETE /api/memory`
- `GET /api/tool-stats`

要求：

- 展示记忆列表
- 支持新增、搜索、删除、清空
- 展示分类和 tags
- 展示工具使用统计

### 6.8 管理中心页

数据接口：

- `GET /api/bots`
- `POST /api/admin/bots`
- `GET /api/admin/bots/{alias}`
- `DELETE /api/admin/bots/{alias}`
- `POST /api/admin/bots/{alias}/start`
- `POST /api/admin/bots/{alias}/stop`
- `PATCH /api/admin/bots/{alias}/cli`
- `PATCH /api/admin/bots/{alias}/workdir`
- `GET /api/admin/bots/{alias}/processing`
- `POST /api/admin/restart`
- `GET /api/admin/scripts`
- `POST /api/admin/scripts/run`

要求：

- 采用表格或卡片形式展示 Bot 列表
- 支持启停、删除、修改工作目录、修改 CLI
- 支持查看当前处理中会话
- 支持执行系统脚本并展示输出
- 支持触发后端重启，并提示用户稍后重新连接

## 7. UI/UX 具体要求

### 风格

- 中文界面
- 工具型产品风格，不要做成营销官网
- 信息密度适中，桌面端优先
- 明确区分：
  - 用户输入
  - AI 输出
  - Shell 输出
  - 错误信息
  - 系统状态

### 反馈

- 所有网络请求都要有 loading 状态
- 所有写操作都要有成功/失败反馈
- 长耗时操作要有持续反馈，不允许无响应

### 响应式

- 桌面端：三栏布局优先
- 移动端：底部切换页签或手风琴结构
- 最小支持宽度 360px

## 8. 技术要求

- 推荐框架：React + TypeScript
- 状态管理可选：Zustand / Redux Toolkit / TanStack Query
- HTTP：统一封装 API Client
- 所有接口错误必须统一处理
- 本地持久化：
  - backend base URL
  - token
  - user id
  - 最近使用的 bot alias

## 9. 联调约定

后端已提供 Web API，返回格式统一为：

成功：

```json
{ "ok": true, "data": {} }
```

失败：

```json
{
  "ok": false,
  "error": {
    "code": "xxx",
    "message": "xxx"
  }
}
```

请求头规范：

- `Authorization: Bearer <token>`
- `X-User-Id: <int>`

## 10. 验收标准

满足以下条件即视为前端可交付：

1. 用户能通过登录页连接后端并完成鉴权。
2. 用户能查看 Bot 列表并进入某个 Bot 的工作台。
3. 在 `cli` 模式下，用户能完成聊天、执行 shell、切换目录、上传下载文件。
4. 在 `assistant` 模式下，用户能完成聊天并管理记忆。
5. 用户能查看当前会话历史，并可重置会话或终止任务。
6. 管理者能在管理中心查看 Bot 状态、启停 Bot、修改工作目录和 CLI 配置。
7. 所有错误都能在前端被明确提示，不出现静默失败。

## 11. 交付物

前端团队需交付：

- 可运行前端工程
- 环境变量说明
- 页面说明文档
- 与后端接口映射表
- 基本联调截图
