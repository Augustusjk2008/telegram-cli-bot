# Plugin System

## 模块和数据

- Plugin 默认位于 `Path.home() / ".tcb" / "plugins"`。
- Manifest：`bot/plugins/manifest.py`、`models.py`；registry/file matching：`registry.py`；进程和 Host API：`runtime.py`、`host_api.py`；编排、view session、cache、artifact 和 audit：`service.py`、`view_sessions.py`、`artifacts.py`、`audit.py`；受 allowlist 约束的外部运行时安装：`runtime_installers.py`。
- Web routes 位于 `bot/web/api_service.py`、`bot/web/server.py`。
- 示例 Vivado waveform plugin 位于 `examples/plugins/vivado-waveform`，运行时复制或同步到用户 plugin 目录。

## 必须保持的行为

- 当前 `plugin.json` 只接受 schema v2；`views[].viewMode`、`views[].dataProfile`、`runtime.permissions`、`runtime.limits`、`configSchema`、`catalogActions` 和 `fileHandlers` 都属于当前 v2 契约。
- Web API 更新 plugin 后写 manifest、清理 view sessions、关闭 runtime；下次访问从磁盘 reload。
- 刷新 plugin 页面会重新扫描 manifest 并重启 runtime。
- Host API 必须按 manifest permission 和 limits 放行 workspace 读取、目录枚举和 artifact 写入；路径必须留在 workspace root 内，artifact 按单个、数量和总大小限额保存。
- 外部 plugin runtime 只允许 allowlist 中的固定下载项；下载使用 HTTPS、校验 SHA-256、限制压缩包大小，拒绝越界路径、符号链接、设备名和不安全文件类型，并以可恢复的目录替换完成安装。
- Plugin service 的失效路径必须同时清理 view sessions、artifacts、snapshot cache、in-flight state 并停止 plugin process；运行时和 Host API 事件写入 audit。
- Vivado backend 使用 Python JSON-RPC stdio，按 source fingerprint 建 VCD index，按需返回可见 time/signal window。
- `config.lodEnabled` 控制 dense-segment LOD；压缩不得隐藏 signal activity。

## 验证

- Runtime/service：`tests/test_plugin_runtime.py`、`tests/test_plugin_service_cache.py`。
- Host API、runtime installer 和 runtime API：`tests/test_plugins_host_api.py`、`tests/test_plugin_runtime_installers.py`、`tests/test_plugin_runtime_api.py`。
- Bundled plugin、artifact、waveform 和文件视图：`tests/test_bundled_plugins.py`、`tests/test_plugin_runtime.py`、`tests/test_vivado_waveform.py` 及对应前端测试。
- 涉及 file view 或 waveform UI 时运行对应前端测试和 build。
