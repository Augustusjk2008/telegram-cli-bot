# Web Chat Markdown Rendering Design

日期：2026-04-10

## 目标

让 Web Bot 聊天界面的助手消息在流式输出结束后默认按 Markdown 渲染；流式过程中继续显示“正在输出”与纯文本预览；若 Markdown 渲染失败，则自动退回原始文本显示。

## 用户确认的约束

- 仅对 Web 端聊天界面的助手最终回复启用 Markdown 渲染。
- 用户消息与系统消息继续保持纯文本显示。
- 流式过程中不做 Markdown 渲染，仍显示纯文本预览和等待状态。
- 最终渲染失败时必须回退到原始文本，而不是显示空白或报错占位。
- 需要同时解决长 Windows 文件路径、长未分词文本在聊天气泡中横向溢出的问题。

## 现状

- [front/src/screens/ChatScreen.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx) 当前对所有聊天消息统一使用纯文本气泡渲染，助手消息完成后仍是 `whitespace-pre-wrap` 文本。
- [front/src/components/MarkdownPreview.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/MarkdownPreview.tsx) 已实现一个用于文件预览的安全 Markdown 渲染器，支持 GFM、自定义代码块、图片路径占位。
- [front/src/test/chat-screen.test.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/chat-screen.test.tsx) 已覆盖聊天页的发送、流式状态、恢复中任务、耗时展示等基础行为，但未覆盖聊天消息 Markdown 渲染与失败回退。
- 当前工作区并非干净基线，相关前端文件已有未提交修改，因此实现必须在现有行为之上增量改动，不能重置或回退文件内容。

## 方案

- 保持后端流式接口与消息数据结构不变，继续由前端根据 `role` 与 `state` 决定渲染方式。
- 流式阶段的助手消息继续显示纯文本内容；如果尚未收到任何文本，则显示“正在输出...”占位。
- 助手消息在 `state !== "streaming"` 时走 Markdown 渲染路径，复用已有 Markdown 组件能力，避免重复定义 Markdown 样式。
- 在聊天页增加一个针对助手消息的包装渲染层，负责：
  - 流式阶段与完成阶段的切换
  - Markdown 渲染异常时的错误边界与纯文本回退
  - 普通文本、内联代码、代码块的断行与宽度约束

## 组件设计

- 保留 [front/src/components/MarkdownPreview.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/MarkdownPreview.tsx) 作为基础 Markdown 呈现组件，并将其扩展为可复用于聊天场景。
- 新增聊天场景的轻量包装组件或本地辅助组件，用于捕获渲染异常并在失败时切换到 `<pre>`/纯文本视图。
- [front/src/screens/ChatScreen.tsx](C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx) 中对消息气泡按角色拆分：
  - 用户消息：维持纯文本气泡
  - 系统消息：维持纯文本气泡
  - 助手消息 `streaming`：纯文本预览
  - 助手消息 `done`：Markdown 渲染，失败时回退纯文本

## 换行与溢出策略

- 助手消息外层 Flex 子项增加可收缩约束，避免内容把气泡宽度撑出容器。
- 普通 Markdown 段落、列表项、引用、表格单元格、图片路径占位需要启用断词样式，确保长路径可换行。
- 行内代码不再强制单行滚动，而是允许在必要时断行。
- 代码块仍保留横向滚动，以避免命令与 diff 内容被强制断行后失去可读性。
- 若消息本身不是合法 Markdown，只要最终能显示原始文本且不横向溢出，即视为满足兼容目标。

## 错误处理

- Markdown 渲染阶段若抛出运行时异常，聊天页不应中断整棵消息列表渲染。
- 失败时回退到纯文本视图，并保持原始消息内容完整可见。
- 回退逻辑仅影响单条助手消息，不影响其他消息与整体聊天状态。

## 测试

- 新增聊天页测试覆盖流式阶段显示“正在输出...”。
- 新增聊天页测试覆盖助手最终回复按 Markdown 渲染标题、列表或代码块。
- 新增测试覆盖助手 Markdown 渲染失败时回退为原始文本。
- 新增样式/布局回归测试，验证超长路径文本不会把聊天界面撑出移动端宽度。
- 保留现有聊天页耗时、恢复中任务、未完成预览恢复等回归验证。
