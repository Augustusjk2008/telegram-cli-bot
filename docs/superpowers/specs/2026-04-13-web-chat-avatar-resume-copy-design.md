# Web Chat Avatar / Resume / Copy Design

日期：2026-04-13

## 目标

优化 Web 聊天体验，覆盖三类能力：

1. 把当前 Web 聊天列表改成更接近真正 IM 的消息样式，显示双方名字、头像和时间。
2. 对“上次异常中断，已恢复最近预览”的场景增加一个一键“继续”按钮，自动发送预设提示词让 AI 判断是否已经说完并继续工作。
3. 在 assistant 完成消息底部，把现有“用时 xx 秒”扩展为“用时 + 复制”操作条，支持一键复制本条 AI 回复。

同时，为 bot 增加可配置头像：

- 头像资源放在前端资产目录中。
- Bot 管理页面允许从资产目录选择头像。
- 选择时显示头像预览，保存的头像名称就是文件名。

## 范围

本次只做 Web 聊天与 Web Bot 管理，不改 Telegram 展示层。

本次包含：

- Web 聊天消息样式升级
- restored running reply 的“继续”操作
- assistant 完成消息复制按钮
- bot 头像数据模型、Bot 管理页头像选择、头像资源枚举接口

本次不包含：

- 头像上传
- 富媒体头像编辑
- 按用户维度自定义头像
- system 消息改造成普通聊天角色

## 现状

### 聊天页

[`front/src/screens/ChatScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx)

当前聊天页特征：

- user / assistant / system 三种消息仅靠气泡对齐和颜色区分
- assistant 完成消息底部只有“用时 xx 秒”
- restored running reply 仅展示一条 system 提示和一条 assistant 预览，不可恢复执行
- assistant 消息本体已经支持 Markdown 渲染

### Bot 管理页

[`front/src/screens/BotListScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/BotListScreen.tsx)

当前 Bot 管理页支持：

- 创建 Bot
- 进入 Bot
- 启停
- 改名
- 删除

但当前没有头像字段，也没有资产枚举与预览能力。

### Web 静态资源

[`bot/web/server.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/server.py)

当前 aiohttp 服务器只对 `front/dist/assets` 暴露 `/assets` 静态路径。

这意味着头像资源如果要被后端 Web 服务稳定访问，最合适的放置方式是：

- 源目录：`front/public/assets/avatars/`
- 构建后：`front/dist/assets/avatars/`
- 访问 URL：`/assets/avatars/<filename>`

## 方案比较

### 方案 A：Bot 保存头像文件名，聊天页按 bot 配置显示

- 在 bot profile 中新增 `avatar_name`
- 前端通过 `/assets/avatars/<avatar_name>` 渲染
- Bot 管理页从资产目录读取可选头像列表

优点：

- 配置明确
- 不受 alias 改名影响
- 适合 Bot 管理页做预览与修改

缺点：

- 需要新增后端字段和一个资产列表接口

### 方案 B：按 alias 自动映射头像文件

- 例如 `team2 -> /assets/avatars/team2.png`

优点：

- 实现最小

缺点：

- 改名即失效
- 管理页无法真正“选择”
- 无法满足“头像名称就是文件名并预览选择”的需求

### 方案 C：做完整资产管理

- 上传、删除、预览、分类、绑定

优点：

- 长期可扩展

缺点：

- 显著超出本次需求

## 已选方案

采用方案 A。

原因：

- 精确满足“头像放在 asset 文件夹、名称就是文件名、管理页可预览选择”的要求。
- 实现成本明显低于完整资产管理。
- 不把头像绑定到 alias，避免后续改名引发无关问题。

## 头像资源规范

头像资源规范在本次设计中直接定死：

- 目录：`front/public/assets/avatars/`
- 推荐格式：`.png`
- 基准尺寸：`64 x 64`
- 显示尺寸：
  - 聊天页消息：`28 x 28`
  - Bot 管理页预览：`32 x 32`
  - Bot 管理列表卡片：`36 x 36`
- 形状：圆形裁切
- 文件名：直接作为 `avatar_name`

默认头像：

- `user-default.png`
- `bot-default.png`

约束：

- 如果所选头像文件不存在，前端一律回退到 `bot-default.png`
- 用户头像不是可配置项，固定使用 `user-default.png`

## 数据模型

### 后端

[`bot/models.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/models.py)

在 `BotProfile` 中新增：

- `avatar_name: str = "bot-default.png"`

并同步更新：

- `to_dict()`
- `from_dict()`

### Web API summary

[`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py)

`build_bot_summary()` 返回中新增：

- `avatar_name`

### 前端类型

[`front/src/services/types.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/types.ts)

在以下类型中新增可选字段：

- `BotSummary.avatarName?: string`
- `BotOverview.avatarName?: string`
- `CreateBotInput.avatarName?: string`

[`front/src/services/realWebBotClient.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/realWebBotClient.ts)

需要把 `avatar_name` 映射成 `avatarName`。

## 后端接口设计

### 1. 新增头像列表接口

新增管理接口，例如：

- `GET /api/admin/assets/avatars`

返回结构：

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "name": "bot-default.png",
        "url": "/assets/avatars/bot-default.png"
      },
      {
        "name": "claude-blue.png",
        "url": "/assets/avatars/claude-blue.png"
      }
    ]
  }
}
```

后端枚举来源：

1. 优先 `front/public/assets/avatars/`
2. 若不存在，则回退 `front/dist/assets/avatars/`

第一版只枚举：

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`

### 2. 新增 Bot 头像更新接口

新增管理接口，例如：

- `PATCH /api/admin/bots/{alias}/avatar`

请求体：

```json
{
  "avatar_name": "claude-blue.png"
}
```

行为：

- 校验文件名只允许基础文件名，不允许路径穿越
- 若文件不存在，返回 400
- 保存到 `BotProfile.avatar_name`
- 返回更新后的 bot summary

### 3. 创建 Bot 时允许指定头像

现有：

- `POST /api/admin/bots`

请求体新增：

- `avatar_name`

未传时默认：

- `bot-default.png`

## 聊天页设计

### 消息元信息

聊天页每条 user / assistant 消息统一显示：

- 头像
- 名称
- 时间
- 消息内容

显示规则：

- user
  - 名称：`你`
  - 头像：`/assets/avatars/user-default.png`
- assistant
  - 名称：当前 `botAlias`
  - 头像：当前 bot 配置头像，若无或无效则 `bot-default.png`
- system
  - 继续保持居中提示，不显示头像，不并入普通聊天流样式

时间格式：

- 本地时间 `HH:mm`
- 使用消息的 `createdAt`

### 完成消息底部操作条

assistant 且 `state !== "streaming"` 且 `state !== "error"` 时，显示底部操作条：

- `用时 xx 秒` 标签
- `复制` 按钮

复制行为：

- 点击后复制该条 assistant 文本原文
- 成功后按钮短暂变为 `已复制`
- 若浏览器复制失败，显示现有 error banner

### 已恢复中断任务卡片

对 restored running reply，不再只塞两条普通消息。

改为：

- 仍保留 user 历史上下文
- 在 assistant 预览气泡下方额外显示恢复操作区
- 恢复操作区包含：
  - 提示文字：`检测到上次异常中断，已恢复最近预览。`
  - `继续` 按钮

显示条件：

- `overview.isProcessing === false`
- 但 `overview.runningReply` 仍存在

点击 `继续` 后：

- 走和普通发送一致的 `handleSend()`
- 发送一条预设文本
- 页面行为和手动输入完全一致

## 继续按钮提示词设计

### 预览截断规则

从 `runningReply.previewText` 提取末尾 48 个字符：

- 去掉首尾空白
- 若为空，使用 `（无预览）`

### CLI Bot 文案

当 `botMode === "cli"` 时自动发送：

```text
上次异常中断了。你最后一段可见输出大致是：
「{preview_tail}」

请先判断你上次是否已经真正说完这件事。
如果这不是你真正说完的结尾，请查看当前会话聊天记录，然后继续完成刚才的工作。
```

### Assistant Bot 文案

当 `botMode === "assistant"` 时自动发送：

```text
上次异常中断了。你最后一段可见输出大致是：
「{preview_tail}」

请先判断你上次是否已经真正说完这件事。
如果这不是你真正说完的结尾，请查看 assistant 历史记录以及工作区里已保存的 assistant 相关记录，然后继续完成刚才的工作。
```

### 为什么区分两种文案

- `assistant` 模式下存在额外的 assistant 持久化上下文与运行时记录
- 普通 `cli` 模式只应提醒它先看当前聊天历史

第一版不把这些路径硬编码成具体文件系统绝对路径文案，只给出稳定的入口提示，避免文案与内部实现过度耦合。

## Bot 管理页设计

### 创建表单

[`front/src/screens/BotListScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/BotListScreen.tsx)

新增字段：

- `头像`

交互：

- 展示当前选择的缩略图
- 通过下拉或选择面板列出可用头像
- 列表项显示：
  - 缩略图
  - 文件名

默认值：

- `bot-default.png`

### 已有 Bot 卡片

每张 Bot 卡片增加头像预览。

同时为已有 Bot 提供“修改头像”入口：

- 不必新开复杂对话框
- 可复用现有 inline 编辑风格
- 允许切换头像并保存

### 切换器

[`front/src/components/BotSwitcherSheet.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/BotSwitcherSheet.tsx)

第一版可选显示头像，但不是本次必须项。

优先级：

1. Bot 管理页
2. 聊天页
3. Bot 切换器

## 前端结构建议

建议新增轻量组件，避免继续把 `ChatScreen.tsx` 做大：

- `front/src/components/ChatAvatar.tsx`
- `front/src/components/ChatMessageMeta.tsx`
- `front/src/components/ChatMessageActions.tsx`
- `front/src/components/RestoredReplyNotice.tsx`
- `front/src/components/AvatarPicker.tsx`

同时可新增工具函数：

- `front/src/utils/chatResume.ts`
  - 提取 preview tail
  - 生成 continue prompt
- `front/src/utils/avatar.ts`
  - 生成头像 URL
  - 处理 fallback

## 错误处理

### 头像

- 配置头像不存在：前端回退到默认头像
- 头像列表接口失败：Bot 管理页显示错误提示并禁用选择器

### 继续按钮

- 自动发送失败：沿用聊天页现有错误 banner
- 若当前已进入 streaming，再次点击继续按钮应禁用

### 复制按钮

- `navigator.clipboard.writeText()` 失败：显示错误 banner
- 不额外引入复杂 toast 系统

## 测试策略

### 前端单元 / 组件测试

新增或扩展：

- [`front/src/test/chat-screen.test.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/chat-screen.test.tsx)
- [`front/src/test/app.test.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/app.test.tsx)

覆盖点：

- user / assistant 消息显示名字、头像、时间
- assistant 完成消息显示“用时 + 复制”
- 点击复制后调用 clipboard API
- restored running reply 显示“继续”按钮
- 点击继续后会发送按 `botMode` 区分的预设文本
- preview tail 截断逻辑正确
- 头像缺失时回退默认头像

### 后端测试

新增或扩展：

- `tests/test_web_api.py`
- `tests/test_manager.py`

覆盖点：

- `avatar_name` 可被创建、持久化、读取、更新
- 头像列表接口只返回合法文件名
- 不允许路径穿越文件名

## 实施顺序

1. 扩展 `BotProfile`、manager 持久化与 Web summary 的 `avatar_name`
2. 增加头像枚举接口与头像更新接口
3. 前端 client/types 接入头像字段与头像列表接口
4. Bot 管理页增加头像选择与预览
5. 聊天页升级为头像/名称/时间布局
6. restored running reply 增加“继续”按钮与提示词逻辑
7. assistant 完成消息增加复制按钮
8. 补齐前后端测试

## 风险与取舍

### 风险

- `ChatScreen.tsx` 当前已偏长，若继续直接堆逻辑，可维护性会继续下降
- 复制 API 在部分环境可能不可用，需要前端错误回退
- 头像资源若只存在 `public` 但未构建到 `dist`，aiohttp 部署环境下会出现资源缺失

### 取舍

- 第一版不做头像上传，只做“从资产目录中选”
- 第一版不把 system 消息改成普通聊天头像消息
- 第一版不做复杂 toast，只复用现有错误反馈
