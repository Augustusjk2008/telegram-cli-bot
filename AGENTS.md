# Agent 指南

Orbit Safe Claw 是 Windows 优先的 Python Web 控制台，把用户消息转发给本地 `claude`、`codex` 或 Pi 原生 agent。以下规则适用于整个仓库。

## 会话与安全边界

- 不得主动关闭、重启、kill 当前 agent 自身，或通过停服务、重启服务等方式让当前 agent 退出。
- 如需重启 `python -m bot`、Web 服务或其它宿主进程，先让用户执行，或取得明确指令。
- 保留用户已有改动；不要用破坏性 Git 命令覆盖不属于当前任务的工作。

## 常用命令

```bash
# 安装 / 启动
bash install.sh
bash start.sh
python -m bot

# 后端
python -m pytest tests -q

# 前端
cd front && npm run test:gate
cd front && npm run build
cd front && npm run lint
```

不要假设仓库内 `venv/` 在所有机器可用。优先使用当前激活的 Python 环境，除非已验证本地 venv。

## 仓库边界

- `bot/` 是后端、Web API、bot manager、native agent 和 plugin 实现；`front/` 是 React/Vite 前端；`tests/` 是后端 pytest。
- 不要提交或 force-add `.env`、真实 `managed_bots.json`、`docs/` 运行态资料和 release notes，以及用户目录 `.tcb/` 下的数据。
- `managed_bots.example.json` 仅作公开示例；当前 runtime 仅 Web，不存在 per-bot Telegram application lifecycle。
- 用户可见文案使用中文。
- Brand/logo 统一使用 `front/public/assets/app-logo*.svg`；login、favicon、mobile shell 和 workbench header 保持一致。
- 配置从 `bot/config.py` 的环境变量加载；`.env` 使用 `python-dotenv`。
- 固定公网转发必须保留 `/node/<节点 ID>/` 路径前缀并支持 WebSocket；配置和 `frps`/`frpc` 最小示例见 `README.md`。

## 核心不变量

- Web session 按 `(bot_id, shared_user_id, agent_id)` 隔离；Web 用户 id 通过 `chat_session_user_id()` 归一化。
- 用户文本以 `//` 开头时改写为 `/...`；Codex CLI 使用 JSON output。
- `execution_mode=native_agent` 使用 AG-UI；普通 CLI 保持 legacy SSE `delta/status/trace/done`。
- CLI SSE 的 `meta/status/trace/done` 顶层必须保留 `turn_id`、`assistant_message_id`，以稳定绑定当前轮。
- 普通 CLI trace 只进入 `ChatTracePanel`；只有原生来源进入 `NativeAgentTranscript`。
- Pi runtime 只能由 `pi_session_runtime.py` 的单 reader 读取 `client.events()`。
- Pi session 绑定由 `cwd + model_id + pi_agent + reasoning_effort` 决定；任一项变化都必须失效旧 session 和 workspace-history rollback 链。

修改 native agent/Pi/cluster、LiteLLM Transfer、Plugin 或安装/发布链路时，使用仓库级 `orbit-maintenance` skill，并只读取与当前子系统对应的 reference。

## CodeGraph

- 跨模块修改、架构分析、重构、调用链或影响面分析先用可用的 CodeGraph 工具；仅对未覆盖或将要修改的具体细节读源码。
- CodeGraph 不可用时直接使用 `rg` 和源码阅读；变更后以测试、日志和 `git diff` 验证。
- 大改动后运行 `codegraph sync .` 刷新索引。

## 验证

- 完成前运行与改动匹配的测试、构建或 smoke check，并报告实际结果；无法运行时说明原因。
- 后端使用 `pytest`、`pytest-asyncio`、`unittest.mock`；当前未配置后端 linter/type checker。
- 前端使用 Vitest、Testing Library 和 Playwright；涉及布局时运行浏览器级检查。
- 避免在 component、page、shell 多层重复断言同一事实，只保留最合适的一层。
