# LiteLLM Transfer 网关

## 模块

- 配置：`bot/web/transfer_litellm_config.py`。
- 子进程运行时：`bot/web/transfer_litellm_runtime.py`。
- 转发、统计、Codex compact 适配：`bot/web/transfer_service.py`。
- 管理路由：`bot/web/routes/transfer_routes.py`。
- Admin Center 入口：`front/src/screens/AdminCenterScreen.tsx`。

## 必须保持的行为

- 网关是可选能力，通过独立 `enabled` 状态启停；配置变化热切换，不要求重启主 Web 服务。
- 每条 route 保留模型别名、LiteLLM model、provider 地址、密钥、`endpoint_mode` 和额外参数。
- `endpoint_mode` 只允许 `auto`、`chat_completions`、`responses`。
- Codex remote compact 经 Responses 入口时，把 LiteLLM 流式结果转换为 Codex compact 事件格式。
- API 状态不得回显上游密钥，只暴露 `provider_api_key_set`。
- 普通 CLI 默认可以继续直连自身 provider；Transfer 不得变成强制依赖。

## 运行态路径

- 配置和日志从 `bot/runtime_paths.py` 的 `get_transfer_litellm_config_path()`、`get_transfer_litellm_log_path()` 获取。
- 默认位于 `~/.tcb/orbit-safe-claw/transfer`；不要在仓库根新增运行态配置或日志。
- Trace 仍由 `TRANSFER_TRACE=1` 控制。

## 验证

- 后端：`tests/test_transfer_service.py`、`tests/test_transfer_routes.py`。
- 涉及 Admin Center 时补跑对应前端测试、`npm run build`。
