# Plugin System

## 模块和数据

- Plugin 位于 `get_tcb_home_root()/plugins`，默认 `~/.tcb/plugins`，存储迁移后跟随定位器。`TCB_DATA_DIR` 单独覆盖应用数据目录时不改变插件根目录。
- Manifest：`bot/plugins/manifest.py`、`models.py`；registry/file matching：`registry.py`；进程和 Host API：`runtime.py`、`host_api.py`；编排、view session、cache、artifact 和 audit：`service.py`、`view_sessions.py`、`artifacts.py`、`audit.py`；受 allowlist 约束的外部运行时安装：`runtime_installers.py`。
- Web 路由注册：`bot/web/routes/plugin_routes.py`；权限和输入校验：`bot/web/plugin_api_service.py`；server handler：`bot/web/server.py`。
- 内置插件来源为 `examples/plugins/`，安装和同步见 `installer.py`、`catalog.py`。临时产物与 audit 当前分别位于 `repo_root/.plugins/artifacts`、`repo_root/.plugins/audit`；存储迁移排除该仓库目录。

## 安装与刷新

- CLI `python -m bot.plugins.installer --repo-root <repo> --all` 或重复 `--plugin <id>` 安装示例插件，已安装项默认跳过；`--force` 显式覆盖。Web 安装、卸载、配置修改要求 `run_plugins`，列表要求 `view_plugins`；自定义 `sourcePath` 还要求本机请求、本机管理员和开发模式。目录安装递归发现 `plugin.json` 并先检查重复 ID/目标目录名。
- 服务初始化或扫描时，只为已安装且源文件内容一致的内置插件同步 manifest，保留已安装的 `enabled` 和 `config`；后端文件不同或缺失时跳过同步。源码更新需通过重新安装复制到运行目录。
- Web API 更新 plugin 会合并配置、写 manifest、立即重新 discover，然后清理 view sessions 并停止该插件进程；后续执行按需启动。
- Web 刷新调用 `reload_plugins()`，只对 manifest 签名变化或被移除的插件执行失效清理；纯后端源码编辑不属于 manifest 签名，刷新不能保证重启该进程。配置更新或覆盖安装走显式失效路径。

## 必须保持的行为

- 当前 `plugin.json` 只接受 schema v2；`views[].viewMode`、`views[].dataProfile`、`runtime.permissions`、`runtime.limits`、`configSchema`、`catalogActions` 和 `fileHandlers` 都属于当前 v2 契约。
- Runtime 当前只支持 `type=python`、`protocol=jsonrpc-stdio`，使用宿主 Python，进程按 `(bot_alias, plugin_id)` 复用，cwd 为插件目录。Host API 的 permission/limits 约束宿主接口；插件进程仍继承宿主环境和操作系统权限。
- Host API 必须按 manifest permission 和 limits 放行 workspace 读取、目录枚举和 artifact 写入；workspace 路径必须留在 root 内，artifact 按单个、数量和总大小限额保存。
- 外部 plugin runtime 只允许 allowlist 中的固定下载项，当前为 `mermaid-visio/graphviz` 的 Windows x64 Graphviz `16.1.0`。下载使用 HTTPS、校验 SHA-256、限制压缩包大小，拒绝越界路径、符号链接、设备名和不安全文件类型，并以可恢复的目录替换完成安装；插件不得自带下载 URL/校验和等安装参数。
- Plugin service 的失效路径清理 view sessions、artifacts、snapshot cache 及关联 in-flight 状态并停止 plugin process；运行时和 Host API 事件写入 audit。snapshot cache 有条目和字节双重 LRU 上限。
- Vivado backend 使用 Python JSON-RPC stdio，按 source fingerprint 建 VCD index，按需返回可见 time/signal window。
- `config.lodEnabled` 控制 dense-segment LOD；压缩不得隐藏 signal activity。

## 验证

- 安装、同步和目录导入：`tests/test_plugin_install.py`；runtime/service/cache：`tests/test_plugin_runtime.py`、`tests/test_plugin_service_cache.py`。
- Host API、runtime installer 和 runtime API：`tests/test_plugins_host_api.py`、`tests/test_plugin_runtime_installers.py`、`tests/test_plugin_runtime_api.py`。
- Bundled plugin、artifact、waveform 和文件视图：`tests/test_bundled_plugins.py`、`tests/test_plugin_runtime.py`、`tests/test_vivado_waveform.py` 及对应前端测试。
- 涉及 file view 或 waveform UI 时运行对应前端测试和 build。
