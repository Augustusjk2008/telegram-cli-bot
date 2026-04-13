# Main Settings Theme / Chat Reading Design

日期：2026-04-13

## 目标

调整 Web 设置页的“界面主题”能力，满足两个新要求：

1. 只有 `main` Bot 的设置页可以修改网页主题。
2. 同一区域同时提供聊天正文的字体与字号设置。

本次设计保持主题与阅读偏好都属于“当前浏览器的全局 Web 偏好”，不引入后端持久化。

## 范围

本次包含：

- 限制只有 `main` Bot 设置页显示主题配置区域
- 在同一区域增加聊天正文字体设置
- 在同一区域增加聊天正文字号设置
- 用前端持久化保存主题、聊天字体、聊天字号
- 让聊天正文统一读取这些阅读偏好

本次不包含：

- Telegram 侧字体或主题设置
- Terminal 字体设置
- 每个 Bot 独立的主题或阅读偏好
- 用户自定义任意字体名或任意字号输入

## 现状

### 主题设置

[`front/src/screens/SettingsScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/SettingsScreen.tsx)

当前设置页无论选中哪个 Bot，都会显示“界面主题”卡片。

[`front/src/app/App.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/app/App.tsx)

当前 `App` 在前端维护 `themeName` 状态，并通过：

- `readStoredUiTheme()`
- `persistUiTheme()`
- `applyUiTheme()`

把主题保存到浏览器本地并应用到整站。

### 聊天字体

[`front/src/components/ChatMarkdownMessage.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/ChatMarkdownMessage.tsx)

[`front/src/components/MarkdownPreview.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/MarkdownPreview.tsx)

聊天正文当前主要写死为：

- `text-[15px]`
- `leading-7`

这意味着：

- 字号不能从设置页调整
- 字体也没有独立的聊天阅读配置

## 方案比较

### 方案 A：主题与聊天阅读都作为全局前端偏好

- 只有 `main` 设置页显示配置入口
- 配置项保存在浏览器 `localStorage`
- 所有 Bot 的 Web 聊天页共用同一套阅读样式

优点：

- 改动面最小
- 与当前主题实现方式一致
- 用户切换 Bot 时阅读体验稳定，不会来回跳

缺点：

- 换浏览器或清缓存不会同步

### 方案 B：主题全局，聊天阅读按 Bot 保存

- 主题仍是全局
- 字体字号按 Bot 分开

优点：

- 每个 Bot 可单独调阅读风格

缺点：

- 切换 Bot 时正文样式突变
- 与“网页整体阅读偏好”不一致
- 状态管理更复杂

### 方案 C：后端持久化主题与聊天阅读

- 由后端保存偏好
- 前端登录后拉取并应用

优点：

- 可跨浏览器同步

缺点：

- 明显超出本次需求
- 需要新增后端接口、模型与权限处理

## 已选方案

采用方案 A。

原因：

- 与现有主题实现一致，最符合当前代码结构。
- 用户真正关心的是当前浏览器里的阅读体验，而不是每个 Bot 一套字体方案。
- 不需要引入新的后端状态与接口。

## 配置设计

### 配置入口

仅当 `botAlias === "main"` 时，在设置页显示新的“界面与阅读”模块。

非 `main` Bot 设置页：

- 不显示主题卡片
- 不显示聊天字体与字号配置
- 继续继承当前浏览器已生效的全局主题与聊天阅读偏好

### 配置项

#### 1. 界面主题

沿用现有主题配置：

- `deep-space`
- `classic`

#### 2. 聊天正文字体

固定为三档枚举，不提供自由输入：

- `sans`: 默认无衬线
- `serif`: 宋体风格
- `mono`: 等宽

建议对应字体栈：

- `sans`: `"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
- `serif`: `"SimSun", "Songti SC", "STSong", serif`
- `mono`: `"Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace`

#### 3. 聊天正文字号

固定为三档枚举：

- `small`
- `medium`
- `large`

建议映射：

- `small`: `14px / 24px`
- `medium`: `15px / 28px`
- `large`: `17px / 32px`

其中 `medium` 对齐当前默认样式，避免已有用户视觉突变。

## 持久化设计

继续使用浏览器 `localStorage`。

保留已有主题 key：

- `web-ui-theme`

新增两个 key：

- `web-chat-body-font-family`
- `web-chat-body-font-size`

读取规则：

- key 缺失或值不合法时，回退默认值
- 默认字体为 `sans`
- 默认字号为 `medium`

## 样式生效范围

“聊天正文”限定为聊天消息气泡中的正文文本，不包含以下区域：

- 发送输入框
- 消息发送者名字
- 时间
- 页头标题
- 操作按钮
- system 消息提示条

本次需要覆盖的正文内容：

- user 普通文本消息
- assistant 已完成 Markdown 消息
- assistant streaming / preview 文本
- assistant error 文本

## 前端架构

### App 状态

[`front/src/app/App.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/app/App.tsx)

`App` 继续作为全局偏好的拥有者，新增两组状态：

- `chatBodyFontFamily`
- `chatBodyFontSize`

职责：

- 初始化读取本地存储
- 更新本地存储
- 把对应 CSS 变量应用到 `document.documentElement`
- 传递给 `SettingsScreen`

### Theme / Reading 工具

[`front/src/theme.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/theme.ts)

继续承载主题相关逻辑，并新增聊天阅读偏好的常量、类型、默认值和读写函数，避免偏好配置散落在多个文件中。

建议新增：

- `type ChatBodyFontFamilyName = "sans" | "serif" | "mono"`
- `type ChatBodyFontSizeName = "small" | "medium" | "large"`
- `readStoredChatBodyFontFamily()`
- `persistChatBodyFontFamily()`
- `readStoredChatBodyFontSize()`
- `persistChatBodyFontSize()`
- `applyChatReadingPreferences()`

### 聊天正文样式

正文样式统一改为读取 CSS 变量，而不是继续把字号写死在组件内部。

建议变量：

- `--chat-body-font-family`
- `--chat-body-font-size`
- `--chat-body-line-height`

应用位置：

- assistant Markdown 渲染容器
- user / assistant 的纯文本正文容器

## 设置页交互

[`front/src/screens/SettingsScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/SettingsScreen.tsx)

设置页交互约束：

- 仅 `main` 显示“界面与阅读”
- 主题仍沿用当前卡片选择样式
- 字体与字号使用简单 `select`
- 用户修改后立即生效，无需额外保存按钮
- 成功后沿用现有 `notice` 提示，例如“聊天正文字体已更新”“聊天正文字号已更新”

## 测试设计

### 前端单测

新增或更新以下验证：

1. `main` 设置页可以看到“界面与阅读”模块。
2. 非 `main` 设置页看不到该模块。
3. 调整字体后，聊天正文容器样式使用对应字体变量。
4. 调整字号后，聊天正文容器样式使用对应字号变量。
5. 重新进入应用时，能从 `localStorage` 恢复主题、字体、字号。

建议覆盖文件：

- [`front/src/test/app.test.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/app.test.tsx)
- [`front/src/test/chat-screen.test.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/chat-screen.test.tsx)

## 风险与约束

### 字体可用性

不同机器未必都安装相同中文字体，因此字体配置必须基于字体栈，而不是单一字体名。

### 主题权限语义

这里只是“只有 `main` 设置页能改”，不是后端权限限制。

也就是说：

- 主题仍是前端全局状态
- 非 `main` 页面只是没有入口
- 如果用户已经在 `main` 改过主题，其他 Bot 页面会直接继承

### 改动边界

本次不扩展到 Terminal 字体、文件页字体、Git 页字体，避免把“聊天阅读偏好”演变成全站排版系统。
