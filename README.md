# Orbit Safe Claw

远程控制 AI 智能体的多 Bot Web 控制台。它把 `codex` / `claude` / `kimi`、项目文件、Git、终端、插件视图、Assistant 自动化和管理中心聚合到同一浏览器界面，用于统一调度多个仓库、子 agent、集群任务和后台维护流程。

## 核心能力

- 多 Bot 编排：主 Bot + 托管 Bot 共同运行，每个 Bot 绑定 CLI、工作目录、运行模式、CLI 参数和独立会话。
- 集群协作：CLI Bot 支持子 agents、`@agent_id` 路由、集群模板、JSON bundle、MCP 连接和模型档位，适合并行分派审查、实现、验证等任务。
- 原生 agent：Chat 支持普通 CLI 和原生 agent 执行模式，保留原生会话复用、上下文用量、工具调用、权限请求和过程详情。
- Assistant Ops：提供 proposal 审批、patch 生成 / dry-run / apply、memory、diagnostics、audit、Automation 队列、cron 和 runs，承载长期维护流程。
- 项目工作台：Chat、Files、Git、Terminal、Debug 组成一体化开发界面，覆盖对话执行、文件编辑、版本控制、终端和系统脚本；Chat 过程详情刷新前后保持一致。
- 插件运行时：基于 `plugin.json` 扩展文件视图、插件配置和进程运行能力，支持 session 型重型视图，内置 Vivado waveform 示例。
- 管理与交付：Admin Center 覆盖用户权限、邀请码、公告发布、更新检查、Release 下载和离线包管理；Cloudflare quick tunnel 支持移动端远程访问。

## 环境要求

- Windows 10 / 11
- Ubuntu / Debian Linux
- macOS 12+（首版为源码包，非 `.app` / DMG）
- Python 3.10+
- Node.js 18+（Pi 原生 agent 需 Node.js 22+）
- Git

## 项目目录

```text
.
├─ bot/                    # Python 后端、Web API、bot manager、native agent、plugins
├─ front/                  # React/Vite 前端，chat/files/git/terminal/admin/plugins UI
├─ examples/plugins/       # 示例插件，如 Vivado waveform、CSV preview
├─ tests/                  # 后端 pytest；含 Web/API、agent、plugin、eval suite 集成测试
├─ agent_eval_suite/       # Agent 评测套件，含 prepare/score/report CLI
├─ scripts/                # 辅助脚本
├─ deploy/                 # 发布/部署相关文件
├─ docs/                   # 本地参考资料和计划文档；通常不提交运行态资料
├─ install.*               # 安装脚本
├─ start.*                 # 启动脚本
├─ suite.py                # agent_eval_suite 的仓库根 CLI shim
├─ managed_bots.example.json
└─ AGENTS.md               # coding agent 工作约定
```

运行态/本地文件：

- `.env`：本机配置，不提交
- `managed_bots.json`：本机托管 bot 配置，不提交真实文件
- `front/dist/`：前端构建产物
- `agent_eval_suite/runs/`：评测 run workspace/report，git 忽略
- `agent_eval_suite/private_gold/<run>/`：评测隐藏答案/checks，git 忽略
- `Path.home()/.tcb/orbit-safe-claw`：默认运行态数据目录，可用 `TCB_DATA_DIR` 覆盖

## 下载与安装

推荐用 GitHub Releases 正式包：

Windows：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 绿色版：下载 `orbit-safe-claw-windows-x64-<version>.zip`，解压后运行 `start.bat`
3. 安装版：下载 `orbit-safe-claw-windows-x64-installer-<version>.zip`，解压后运行 `install.bat`

Windows 绿色版已带 Python、Git 和前端构建产物，无需安装 Python / Node / Git；不内置 AI CLI。使用前需本机可运行 `codex --version` / `claude --version` / `kimi info`，并可在 Web 设置页或 `.env` 修改 `CLI_TYPE` / `CLI_PATH`。

Pi 原生 agent 需额外满足：Node.js 22+、Pi CLI、Windows Git Bash。若 `pi` 不在 PATH，设置 `NATIVE_AGENT_PI_COMMAND` 为可执行文件路径。运行态数据默认在用户目录 `.tcb/orbit-safe-claw`；如设置 `TCB_DATA_DIR`，建议放 workspace 外，避免 workspace rollback 影响运行状态。Pi workspace history 默认不再在 preflight 阶段直接降级，插件可用性和锁文件改在运行时校验；rollback 失败只影响回滚能力，不阻断已完成回复。Pi workspace rollback 会丢弃目标 turn 之后记录，无 redo。

Linux：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新 `orbit-safe-claw-linux-x64-<version>.tar.gz`
3. 解压后运行 `bash install.sh`

macOS：

1. 打开 <https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest>
2. 下载最新 `orbit-safe-claw-macos-universal-<version>.tar.gz`
3. 解压后运行：

```bash
tar -xzf orbit-safe-claw-macos-universal-<version>.tar.gz
cd orbit-safe-claw
bash install.sh
bash start.sh
```

macOS 需要 Python 3.10+、Node.js 18+、Git，推荐先装 Homebrew；Pi 原生 agent 需 Node.js 22+。AI CLI 不内置，需自行安装 `codex` / `claude` / `kimi`。

源码快照安装：

Windows：

```powershell
$zip="$env:TEMP\\orbit-safe-claw.zip"; Invoke-WebRequest "https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.zip" -OutFile $zip; Expand-Archive $zip -DestinationPath . -Force; Set-Location .\telegram-cli-bot-master; .\install.bat
```

Linux：

```bash
curl -L https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.tar.gz | tar -xz && cd telegram-cli-bot-master && bash install.sh
```

macOS：

```bash
curl -L https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.tar.gz | tar -xz && cd telegram-cli-bot-master && bash install.sh
```

安装器会准备：

- Python / Node.js / Git 检查
- 后端依赖
- 前端依赖和构建
- `.env`

安装器会检查本机 `codex` / `claude` / `kimi` 可用性，并给出后续配置提示。

## 如何运行

Windows：

- 双击 `start.bat`
- 或终端运行 `.\start.bat`

Linux：

- 运行 `bash start.sh`

macOS：

- 运行 `bash start.sh`

首次启动时，Windows 的 `start.bat` / `start.ps1` 会自动补齐 `.env` 配置，再继续启动。

默认 Web 绑定地址 `0.0.0.0:8765`，本机访问可用 `http://127.0.0.1:8765`。登录口令使用 `.env` 里的 `WEB_API_TOKEN`。

如果 `.env` 里的 `WEB_PORT` 已被占用，启动时会自动尝试 `+1`，直到找到可用端口；控制台、健康检查和 tunnel 都会跟随实际端口。

如果启用了 `WEB_TUNNEL_MODE=cloudflare_quick` 且 tunnel 拉起成功，控制台会打印公网地址二维码，方便手机扫码打开。

Web 终端默认在后端启动系统 shell：Windows 为 PowerShell，Linux 为 `bash`，macOS 为 `$SHELL` 或 `/bin/zsh`。如需指定 shell 可执行文件，设置：

```env
WEB_TERMINAL_SHELL_PATH=/usr/bin/zsh
```

Windows 可写 `C:\Program Files\PowerShell\7\pwsh.exe`。这里配置的是 Web xterm 内运行的 shell，不是外部 GUI 终端窗口。

## 固定公网地址和反向代理

如果你有固定 IP 服务器，可用反向代理把公网路径转到运行 Orbit Safe Claw 的机器。建议每台机器使用一个独立子路径：

```text
http://<固定IP>:18088/node/<节点ID>/
```

本机 `.env` 示例：

```env
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=change-this-password
TCB_NODE_ID=my-laptop
WEB_BASE_PATH=/node/my-laptop
WEB_PUBLIC_URL=http://<固定IP>:18088/node/my-laptop
WEB_TUNNEL_MODE=disabled
```

`VITE_BASE_PATH` 和 `VITE_API_BASE_URL` 留空会跟随 `WEB_BASE_PATH`；如手动填写，必须和 `WEB_BASE_PATH` 相同。改了 `WEB_BASE_PATH` 或 `VITE_*` 后需重新构建前端并重启 Web：

```bash
cd front && npm run build
python -m bot
```

公网服务器需要：

- 放通公网访问端口，如 `18088`
- 能访问本机 Web 地址，如 `http://127.0.0.1:8765` 或内网 / 隧道端口
- 保留 `/node/<节点ID>/` 路径前缀转发，不要在反代层剥掉
- 支持 WebSocket Upgrade，终端、调试和通知会用到

如果 Orbit Safe Claw 直接跑在公网服务器上，反代到 `127.0.0.1:8765` 即可。如果它跑在家用电脑或内网机器上，推荐用 frp：公网服务器运行 `frps`，本机运行 `frpc`，再让反代转到 `frps` 的 HTTP 入口。

公网服务器 `frps.toml` 最小示例：

```toml
bindPort = 7000
vhostHTTPPort = 18765
auth.token = "<frps-token>"
```

本机启用内置 frpc 自动转发时，追加这些 `.env`：

```env
WEB_FIXED_PUBLIC_FORWARD_ENABLED=true
WEB_FIXED_PUBLIC_FORWARD_URL=http://<固定IP>:18088/node/my-laptop
TCB_HUB_FRPS_PORT=7000
TCB_HUB_FRPS_TOKEN=<frps-token>
TCB_HUB_NODE_TOKEN=<random-node-token>
TCB_HUB_FRPC_PATH=frpc
TCB_HUB_FRPC_AUTOSTART=true
```

`TCB_HUB_FRPC_PATH` 留空或写 `frpc` 时，会从 `PATH` 查找；也可写绝对路径，如 Windows 的 `C:\tools\frp\frpc.exe`、Linux / macOS 的 `/usr/local/bin/frpc`。路径不要写 `~` 或 shell alias。

frpc 安装方式：

- 打开 <https://github.com/fatedier/frp/releases>，下载匹配系统和 CPU 的压缩包
- Windows：解压后把 `frpc.exe` 所在目录加入 `PATH`，或把完整路径写入 `TCB_HUB_FRPC_PATH`
- Linux：解压后运行 `sudo install -m 755 frpc /usr/local/bin/frpc`
- macOS：解压后运行 `sudo install -m 755 frpc /usr/local/bin/frpc`；如被 Gatekeeper 拦截，执行 `sudo xattr -d com.apple.quarantine /usr/local/bin/frpc`
- 安装后运行 `frpc --version` 验证

Caddy 示例：

```caddyfile
:18088 {
  handle /node/my-laptop/* {
    reverse_proxy 127.0.0.1:18765
  }
}
```

Nginx 示例：

```nginx
map $http_upgrade $connection_upgrade {
  default upgrade;
  '' close;
}

server {
  listen 18088;

  location /node/my-laptop/ {
    proxy_pass http://127.0.0.1:18765;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
  }
}
```

上例 `127.0.0.1:18765` 是 `frps` 的 `vhostHTTPPort`。如果服务直接跑在公网服务器上，可改成 `127.0.0.1:8765`，并不启用 `WEB_FIXED_PUBLIC_FORWARD_ENABLED`。

## 基本配置

首次安装后至少确认这些 `.env` 项：

```env
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=C:\Users\YourName\project
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=change-this-password
```

如需托管更多 Bot，可参考仓库内 `managed_bots.example.json` 新建本地 `managed_bots.json`：

```json
{
  "bots": [
    {
      "alias": "repo2",
      "cli_type": "codex",
      "cli_path": "codex",
      "working_dir": "C:/work/repo2",
      "enabled": true,
      "bot_mode": "cli"
    },
    {
      "alias": "assistant1",
      "cli_type": "codex",
      "cli_path": "codex",
      "working_dir": "C:/work/assistant-home",
      "enabled": true,
      "bot_mode": "assistant"
    }
  ]
}
```

运行模型：

- `cli` Bot 支持子 agent 和集群配置
- `assistant` Bot 走宿主管理流程，工作目录下会维护 `.assistant/`
- `assistant` Bot 采用单实例宿主模型

## 工作界面

- `cli` Bot：把 Web 消息转发到本地 `codex` / `claude` / `kimi`，支持普通 CLI 和原生 agent 执行模式，保留会话、trace、上下文用量、CLI 参数和子 agent 作用域。
- `assistant` Bot：走宿主管理流程，在工作目录下维护 `.assistant/`，用于长期记忆、任务编排和自动化维护。
- Desktop Workbench：面向重复开发操作，集中承载文件树、编辑器、Git、终端、聊天和插件视图。
- Admin Center：面向运维管理，集中承载账号权限、邀请、公告和更新。

## 更新

主 Bot 设置页和管理中心支持 GitHub Release 自动检查、下载更新和离线包查看。下载后的更新会在下次启动或重启后生效。

更新包按平台匹配：Windows 安装版 / 绿色版、Linux、macOS。macOS 离线包名形如 `orbit-safe-claw-macos-universal-<version>.tar.gz`。

首次安装生成的 `.env` 默认写入：

```env
APP_UPDATE_REPOSITORY=Augustusjk2008/telegram-cli-bot
```

如果你用自己的 GitHub Releases 仓库，改成对应 `owner/repo` 即可。

## 开发命令

```bash
python -m bot
python -m pytest tests -q
cd front && npm test
cd front && npm run build
cd front && npm run lint
```

常用聚焦测试：

```bash
python -m pytest tests/test_web_api.py -q
python -m pytest tests/test_assistant.py -q
python -m pytest tests/test_native_agent.py tests/test_native_agent_context_usage.py tests/test_sessions.py -q
cd front && npm test -- --run src/test/chat-screen.test.tsx src/test/desktop-bot-manager-screen.test.tsx
cd front && npm test -- --run src/test/real-client.test.ts src/test/ag-ui-stream-adapter.test.ts src/test/chat-screen.test.tsx
```

## Agent Eval Suite

本仓库内置 `agent_eval_suite/`，用于评测本地 coding agent。仓库根的 `suite.py` 提供入口：

```powershell
python -m suite prepare --suite-root agent_eval_suite --run run001 --preset win-native --samples 50
python -m suite score --suite-root agent_eval_suite --run run001
python -m suite report --suite-root agent_eval_suite --run run001
```

生成后，把 agent 工作目录设为：

```text
agent_eval_suite\runs\run001\workspace
```

让 agent 按 `PROMPT.md` 读 `tasks/*.jsonl`，写 `answers/*.jsonl`。隐藏答案在 `agent_eval_suite/private_gold/<run>/`，不进入 workspace。

Hard preset 会额外生成真实文件操作题：

```powershell
python -m suite prepare --suite-root agent_eval_suite --run run002 --preset win-native-hard --samples 20
python -m suite score --suite-root agent_eval_suite --run run002 --evalplus-timeout 1.0
python -m suite report --suite-root agent_eval_suite --run run002
```

`workspace_ops` 任务位于 `runs/<run>/workspace/tasks/workspace_ops.jsonl`，可见项目位于 `runs/<run>/workspace/cases/<id>/`，agent 需写 `answers/workspace_ops.jsonl`。详见 `agent_eval_suite/README.md`。
