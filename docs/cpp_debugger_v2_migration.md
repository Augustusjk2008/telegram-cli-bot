# C++ Debugger V2 Migration

## V1 无需改动

老工作区只要仍有：

- `debug.ps1`
- `.vscode/launch.json`
- 可选 `.vscode/c_cpp_properties.json`

即可继续运行。缺少 `spec_version` 时，后端按 V1 解析并归一化为 `DebugProfileV2`。

## V1 字段映射

- `launch.program` -> `target.program`
- `launch.cwd` -> `target.cwd`
- `launch.miDebuggerPath` -> `gdb.path`
- `launch.setupCommands` -> `gdb.setup_commands`
- `launch.stopAtEntry` -> `ui.stop_at_entry`
- `debug.ps1 RemoteHost` / `miDebuggerServerAddress` -> `remote.host`
- `debug.ps1 RemoteGdbPort` / `miDebuggerServerAddress` -> `remote.port`
- `debug.ps1 RemoteUser` -> `remote.user`
- `debug.ps1 RemoteDir` -> `remote.dir`
- 默认准备命令 -> `prepare.command = .\debug.bat`

## 可选升级到 V2

在工作区根目录新增 `debug.json`：

```json
{
  "spec_version": 2,
  "name": "Remote C++ Debug",
  "language": "cpp",
  "target": {
    "type": "remote-gdbserver",
    "architecture": "aarch64",
    "program": "${workspaceFolder}/build/aarch64/Debug/MB_DDF",
    "cwd": "${workspaceFolder}"
  },
  "prepare": {
    "command": ".\\debug.bat",
    "timeout_seconds": 300
  },
  "remote": {
    "host": "192.168.1.29",
    "user": "root",
    "dir": "/home/sast8/tmp",
    "port": 1234
  },
  "gdb": {
    "path": "D:\\Toolchain\\aarch64-none-linux-gnu-gdb.exe",
    "setup_commands": [
      { "text": "-enable-pretty-printing", "ignore_failures": true }
    ]
  },
  "source_maps": [
    { "remote": "/home/sast8/tmp", "local": "${workspaceFolder}" }
  ]
}
```

## 注意

- 密码只从 UI 本次 launch payload 传入，不持久化。
- `prepare.command` 支持 `${remoteHost}`、`${remoteUser}`、`${remoteDir}`、`${remotePort}`、`${password}`。
- `??:0` 属于无源码定位，不会打开空文件。
