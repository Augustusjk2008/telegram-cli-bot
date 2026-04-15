# Files Browser / Workdir Separation Design

日期：2026-04-15

## 目标

调整 Web 文件页行为，满足两个要求：

1. 文件页切换目录时，不再修改 Bot 的真实工作区。
2. Bot 的真实工作区只能通过设置页修改。

同时补一个小的交互改动：

3. 文件列表中的文件项新增下载按钮，位置在删除按钮之前，前后端实现复用现有文件预览弹窗里的下载能力。

## 范围

本次包含：

- 将文件页目录切换统一改成“当前登录用户的文件浏览目录”
- 保持聊天、终端、Git、原生历史定位继续使用真实工作区
- 让文件页 Home 按钮真正回到真实工作区
- 设置页修改工作区后，同步重置当前用户的文件浏览目录
- 文件列表增加下载按钮，顺序为“下载”在前，“删除”在后
- 补后端、前端、mock client、测试

本次不包含：

- 新增独立的文件浏览 API 路由命名
- 每个文件夹额外的收藏、书签或历史记录
- 多用户共享文件页浏览目录
- 改动文件预览弹窗已有下载逻辑

## 现状

### 后端目录状态

[`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py)

当前已有 `browse_dir` 机制，但 `change_working_directory()` 只在 `assistant` 模式下把“文件浏览目录”和“真实工作区”分开。

对 `cli` Bot，当前行为仍然是：

- 修改 `session.working_dir`
- 对子 Bot 还会修改 `profile.working_dir`
- 清理 CLI session id

这导致文件页切目录会直接改变 Bot 的真实工作区。

### 前端文件页

[`front/src/screens/FilesScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/FilesScreen.tsx)

当前文件页进入子目录、返回上级目录都调用 `changeDirectory()`。

Home 按钮当前只是重新加载目录列表，不会真正回到真实工作区。

### 设置页

[`front/src/screens/SettingsScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/SettingsScreen.tsx)

设置页已经通过单独的 `updateBotWorkdir()` 修改真实工作区，天然适合作为唯一正式入口。

## 方案比较

### 方案 A：复用现有 `/cd` 接口，但语义改为“文件浏览目录切换”

- 后端对所有 `cli` / `assistant` Bot 一律只修改当前用户 session 的 `browse_dir`
- 真实工作区继续由设置页接口单独维护
- 文件页 Home 显式把 `browse_dir` 重置到真实工作区

优点：

- 改动最小
- 与当前已有 `browse_dir` 机制一致
- 能满足“按当前登录用户持久化”的要求

缺点：

- `change_working_directory()` 这个函数名会继续沿用旧名字，语义不够理想

### 方案 B：新增专门的文件浏览接口

- 例如新增 `/files/cd`、`/files/home`
- 现有 `/cd` 保留给真实工作区

优点：

- 语义最清晰

缺点：

- 前后端接口改动更多
- 对当前需求来说收益不够

### 方案 C：只在前端维护浏览目录

- 文件页路径不落后端
- 刷新后重新回到真实工作区

优点：

- 实现表面最简单

缺点：

- 不满足“当前登录用户持久化”
- 与后端现有文件读写接口不一致

## 已选方案

采用方案 A。

原因：

- 需求本质是把“文件浏览状态”与“Bot 工作区配置”解耦，而不是重做一套文件 API。
- 后端已经有 `browse_dir` 字段，直接扩展到 `cli` Bot 风险最低。
- 可以最小范围修复现有错误耦合，并保持设置页作为唯一真实工作区入口。

## 设计

### 1. 状态边界

真实工作区：

- 来源于 `profile.working_dir`
- 映射到 `session.working_dir`
- 被聊天、终端、Git、原生历史定位使用
- 只能由设置页修改

文件浏览目录：

- 存在于当前登录用户的 `session.browse_dir`
- 文件页列目录、读文件、上传、删除、新建文件夹全部使用它
- 允许相对路径切换
- 需要持久化，以便当前用户刷新或重新登录后恢复

默认规则：

- 当 `browse_dir` 为空时，文件页默认从真实工作区开始

### 2. 文件页切目录

`change_working_directory()` 调整为统一行为：

- 不再按 `bot_mode` 分叉处理
- 不再修改 `profile.working_dir`
- 不再修改 `session.working_dir`
- 不再因为文件页切目录而清理 CLI session id
- 只更新 `session.browse_dir`

返回值仍保留：

- `{"working_dir": <当前浏览目录>}`

这样前端无需改接口形状。

### 3. Home 按钮

文件页 Home 按钮不再只是 reload。

它应该显式把文件浏览目录重置到真实工作区。实现方式：

- 前端先读取真实工作区
- 再调用现有 `changeDirectory()` 把浏览目录切回真实工作区
- 然后刷新目录列表

这样能保证：

- 用户在文件页深层目录时，点 Home 一定回到真实工作区
- 不需要新增专门 `/home` 路由

### 4. 设置页保存工作区

设置页修改工作区成功后：

- `profile.working_dir` 更新
- 该 Bot 的各用户 session 的 `working_dir` 更新
- 同时把这些 session 的 `browse_dir` 对齐到新的真实工作区

这样可以避免：

- 文件页仍停留在旧路径
- 旧浏览目录越过新的工作区基线

### 5. 文件列表下载按钮

文件列表中的文件项新增下载按钮：

- 仅文件显示，文件夹不显示
- 顺序：下载按钮在删除按钮之前
- 交互直接调用现有 `client.downloadFile(botAlias, file.name)`

后端不新增实现：

- 直接复用已有下载接口
- 与文件预览弹窗下载逻辑保持一致

## 测试

后端测试需要覆盖：

- `cli` Bot 调用 `change_working_directory()` 后，只更新 `browse_dir`
- `session.working_dir` 不变
- `profile.working_dir` 不变
- CLI session id 不会被清掉
- `get_working_directory()` 继续返回真实工作区
- `get_directory_listing()` 继续返回浏览目录
- 设置页改工作区后，浏览目录跟随重置

前端 / mock 测试需要覆盖：

- mock client 的 `changeDirectory()` 不再改 `BotSummary.workingDir`
- 文件页 Home 按钮能回到真实工作区
- 文件列表下载按钮出现于删除按钮之前，并调用已有下载逻辑

## 风险与处理

风险 1：现有前端把 `workingDir` 同时当成“真实工作区”和“当前文件浏览目录”。

处理：

- 保持文件列表接口继续返回当前浏览目录
- 保持设置页 overview 继续显示真实工作区
- 不混用两类接口返回值

风险 2：已有测试默认认为 `cli` 文件页切目录会改变真实工作区。

处理：

- 直接把这些测试改成新语义
- 增补“不影响 CLI session id”的回归测试

风险 3：Home 按钮只 reload 的旧行为会让用户误以为已经回到根目录。

处理：

- 明确改成真实重置动作
- 用前端测试锁定行为
