# C++ Debugger Spec v2

## 目标

v2 在 v1 的远端 `gdbserver` 调试能力上继续扩展，目标是把“单工程单会话调试”升级为“多目标、可恢复、桌面和移动共用”的调试平台。

## 兼容

- v1 配置继续可用，缺少 `spec_version` 时按 v1 解析。
- v2 配置显式写 `spec_version: 2`。
- v1 字段名保留，v2 新字段只做增量读取。
- 后端返回 `capabilities`，前端按能力显示按钮和面板。

## 配置模型

配置入口仍来自工作区调试配置，但内部统一成 `DebugProfileV2`。

```json
{
  "spec_version": 2,
  "name": "MB_DDF Remote Debug",
  "language": "cpp",
  "target": {
    "type": "remote-gdbserver",
    "architecture": "aarch64",
    "program": "${workspaceFolder}/build/aarch64/Debug/MB_DDF",
    "cwd": "${workspaceFolder}",
    "args": [],
    "env": {}
  },
  "prepare": {
    "command": ".\\debug.bat",
    "timeout_seconds": 300,
    "problem_matchers": ["cmake", "gcc"]
  },
  "remote": {
    "host": "192.168.1.29",
    "user": "root",
    "dir": "/home/sast8/tmp",
    "gdbserver": "/home/sast8/tmp/gdbserver",
    "port": 1234
  },
  "gdb": {
    "path": "aarch64-none-linux-gnu-gdb.exe",
    "sysroot": "",
    "setup_commands": [
      { "text": "-enable-pretty-printing", "ignore_failures": true },
      { "text": "set print thread-events off", "ignore_failures": true }
    ]
  },
  "source_maps": [
    { "remote": "/home/sast8/tmp", "local": "${workspaceFolder}" },
    { "remote": "H:/Resources/RTLinux/Demos/MB_DDF", "local": "${workspaceFolder}" }
  ],
  "ui": {
    "stop_at_entry": true,
    "open_source_on_pause": true,
    "default_panels": ["source", "stack", "variables", "console"]
  }
}
```

## 调试生命周期

状态机固定为：

1. `idle`
2. `preparing`
3. `deploying`
4. `starting_gdb`
5. `connecting_remote`
6. `paused`
7. `running`
8. `terminating`
9. `error`

每个阶段都要：

- 可取消。
- 有超时。
- 输出结构化日志。
- 失败时返回可显示的错误码和原始命令。

`prepare.command` 是调试前唯一入口。v2 不再在前端硬编码构建或部署命令，前端只展示和提交该命令。

## GDB/MI 协议

后端统一封装 GDB/MI，前端只消费调试事件。

事件类型：

- `state`: 当前状态快照。
- `prepareLog`: 准备阶段输出。
- `stopped`: 线程暂停，含 frame、reason、source、line。
- `running`: 程序继续运行。
- `breakpoint`: 断点新增、移除、校验结果。
- `variables`: 变量列表更新。
- `console`: GDB 控制台输出。
- `error`: 结构化错误。

命令必须有 `request_id`，返回事件里保留该 id，避免前端按钮状态错乱。

## 源码定位

暂停时后端按顺序解析源码路径：

1. GDB 返回的绝对本地路径。
2. `source_maps` 映射。
3. `compile_commands.json` 的 `directory + file`。
4. 工作区内按文件名候选搜索。

若只解析到 `??:0`，后端保留栈帧但不强行打开源码，前端显示“无源码定位”。

## 断点

v2 断点模型：

- 行断点。
- 函数断点。
- 条件断点。
- 命中次数断点。
- 日志断点。

断点先进入 `pending`，GDB 校验后变为 `verified` 或 `rejected`。前端必须显示拒绝原因。

## 数据视图

变量面板采用懒加载：

- `scopes(frame_id)` 返回作用域。
- `variables(reference)` 返回子节点。
- 支持 `evaluate(expression, frame_id)`。
- 支持寄存器、内存和反汇编，但作为可选 capability。

## 多线程

v2 需要显示：

- 线程列表。
- 当前线程。
- 每线程栈帧。
- 线程切换。

`set scheduler-locking` 不由前端默认设置，只作为高级选项。

## 桌面 UI

桌面保留当前主布局，新增：

- 顶部小图标调试工具条。
- 可折叠会话配置和远端参数。
- 自动打开暂停源码。
- 当前执行行和断点 gutter。
- 调试控制台支持输入 GDB 命令。

## 移动 UI

移动端采用单页调试面板：

- 顶部为状态和小图标工具条。
- 配置区默认折叠。
- 源码、调用栈、变量、日志用 tabs。
- 源码只读，断点可点 gutter。
- 长日志分段虚拟滚动。

移动端不做复杂内存/反汇编编辑，只显示只读视图。

## 错误码

统一错误码：

- `unsupported_language`
- `prepare_failed`
- `prepare_timeout`
- `program_missing`
- `ssh_failed`
- `deploy_failed`
- `gdb_missing`
- `gdbserver_unreachable`
- `source_not_found`
- `gdb_command_failed`
- `session_conflict`

错误响应必须包含：

- `code`
- `message`
- `phase`
- `command`
- `details`

## 安全

- 前端展示命令前做敏感字段脱敏。
- SSH 密码不入库，优先复用系统 ssh key。
- WebSocket 调试接口必须复用现有 Web 鉴权。
- 同一 bot 同一用户只允许一个活跃调试会话。

## API

新增或稳定这些接口：

- `GET /api/bots/{alias}/debug/profile`
- `PATCH /api/bots/{alias}/debug/profile`
- `GET /api/bots/{alias}/debug/state`
- `POST /api/bots/{alias}/debug/launch`
- `POST /api/bots/{alias}/debug/stop`
- `POST /api/bots/{alias}/debug/control`
- `POST /api/bots/{alias}/debug/breakpoints`
- `POST /api/bots/{alias}/debug/evaluate`
- `GET /debug/ws?alias={alias}`

## 测试

后端：

- profile v1 到 v2 兼容解析。
- prepare 命令超时、失败、取消。
- GDB/MI stopped/running 事件解析。
- source map 路径映射。
- 断点 verified/rejected。

前端：

- 桌面工具条按钮状态。
- 移动 tab 和配置折叠。
- 暂停后打开源码并标执行行。
- `??:0` 不打开错误文件。
- WebSocket 断线后恢复状态。

## 落地阶段

1. v2 profile loader：保留 v1 兼容，输出统一 `DebugProfileV2`。
2. lifecycle 分层：prepare、deploy、gdb、session 状态拆清。
3. source map：解决远端路径、Windows 路径和 compile commands。
4. breakpoint v2：增加 pending/verified/rejected。
5. variables lazy loading：支持嵌套变量和 evaluate。
6. mobile parity：移动端补断点、变量展开和日志虚拟滚动。
7. advanced views：线程、寄存器、内存、反汇编按 capability 开启。
