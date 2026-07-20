# Plugin System

## 模块和数据

- Plugin 默认位于 `Path.home() / ".tcb" / "plugins"`。
- Manifest：`bot/plugins/manifest.py`；registry/file matching：`registry.py`；进程：`runtime.py`；编排和 cache：`service.py`。
- Web routes 位于 `bot/web/api_service.py`、`bot/web/server.py`。
- 示例 Vivado waveform plugin 位于 `examples/plugins/vivado-waveform`，运行时复制或同步到用户 plugin 目录。

## 必须保持的行为

- `plugin.json` 同时支持 schema v1、v2。
- v1 包含 `enabled`、可变 `config`、`views[].viewMode` 和 `views[].dataProfile`。
- v2 增加 runtime permissions、`configSchema`、`catalogActions`。
- Web API 更新 plugin 后写 manifest、清理 view sessions、关闭 runtime；下次访问从磁盘 reload。
- 刷新 plugin 页面会重新扫描 manifest 并重启 runtime。
- Vivado backend 使用 Python JSON-RPC stdio，按 source fingerprint 建 VCD index，按需返回可见 time/signal window。
- `config.lodEnabled` 控制 dense-segment LOD；压缩不得隐藏 signal activity。

## 验证

- Runtime/service：`tests/test_plugin_runtime.py`、`tests/test_plugin_service_cache.py`。
- Host API 和 bundled plugin：`tests/test_plugins_host_api.py`、`tests/test_bundled_plugins.py`。
- 涉及 file view 或 waveform UI 时运行对应前端测试和 build。
