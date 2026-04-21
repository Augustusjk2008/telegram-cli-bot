# C++ Debugger Spec v2

## 配置

后端统一输出 `DebugProfileV2`。V1 `.vscode/launch.json + debug.ps1` 继续可用；存在 `spec_version: 2` 时优先读 `debug.json`、`.vscode/debug.json`、`.vscode/launch.json`。

V2 主要字段：

- `target`: `type`、`architecture`、`program`、`cwd`、`args`、`env`
- `prepare`: `command`、`timeout_seconds`、`problem_matchers`
- `remote`: `host`、`user`、`dir`、`gdbserver`、`port`
- `gdb`: `path`、`sysroot`、`setup_commands`
- `source_maps`: `{ remote, local }[]`
- `capabilities`: `threads`、`variables`、`evaluate`、`memory`、`registers`、`disassembly`

`GET /api/bots/{alias}/debug/profile` 保留 V1 snake_case 字段，并新增 `specVersion`、`target`、`prepare`、`remote`、`gdb`、`sourceMaps`、`capabilities`。

## 生命周期

状态固定为：

`idle -> preparing -> deploying -> starting_gdb -> connecting_remote -> paused|running -> terminating|error`

启动顺序：

1. 读取 profile
2. 合并 UI overrides
3. 停止旧 runtime
4. 执行 `prepare.command`
5. 重新读取 profile
6. 校验 `target.program`
7. 启动 GDB
8. 执行 setup commands
9. 连接远端 gdbserver
10. 恢复断点
11. 按 `stopAtEntry` 运行到入口

## 事件

WebSocket `/debug/ws?alias={alias}` 继续推：

- `state`
- `prepareLog`
- `stopped`
- `running`
- `breakpoint` / `breakpoints`
- `stackTrace`
- `scopes`
- `variables`
- `evaluate`
- `console`
- `error`

`prepareLog.payload` 为结构化对象：`type`、`line`、`redacted`、`phase`、`timestamp`。旧文本行兼容仍保留在后端包装层。

## REST API

- `GET /api/bots/{alias}/debug/profile`
- `PATCH /api/bots/{alias}/debug/profile`
- `PATCH /api/bots/{alias}/debug/profile-overrides`
- `GET /api/bots/{alias}/debug/state`
- `POST /api/bots/{alias}/debug/launch`
- `POST /api/bots/{alias}/debug/stop`
- `POST /api/bots/{alias}/debug/command`
- `POST /api/bots/{alias}/debug/control`
- `POST /api/bots/{alias}/debug/breakpoints`
- `POST /api/bots/{alias}/debug/evaluate`

## 源码解析

暂停时按顺序解析：

1. GDB 本地绝对路径且文件存在
2. `source_maps`
3. `remote.dir -> workspace`
4. `compile_commands.json`
5. workspace 文件名搜索

`??`、空路径、`line <= 0` 返回 unresolved，前端不自动打开文件。

## 错误

错误 payload 含：

- `code`
- `message`
- `detail` / `details`
- `phase`
- `command`
- `recoverable`
- `logsTail`

当前错误码包括：`unsupported_language`、`prepare_failed`、`prepare_timeout`、`prepare_cancelled`、`prepare_spawn_failed`、`program_missing`、`ssh_failed`、`deploy_failed`、`gdb_missing`、`gdbserver_unreachable`、`source_not_found`、`gdb_command_failed`、`session_conflict`。

## 手工验收

- 无可执行文件时点启动，先跑 `.\debug.bat`，再报 `program_missing`。
- 准备日志不显示密码。
- `SIGRTMIN` 且 `ignoreFailures: true` 不阻断。
- Windows GDB/MI 路径保留反斜杠。
- 初始 `??:0` 不打开文件；运行到 `main` 后打开源码。
- 桌面和移动端都可启动、继续、暂停、单步、停止。
