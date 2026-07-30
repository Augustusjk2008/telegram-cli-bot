<p align="center">
  <img src="front/public/assets/app-logo.svg" width="112" alt="Orbit Safe Claw Logo">
</p>

<p align="center">
  <strong>简体中文</strong> · <a href="README.en.md">English</a>
</p>

<h1 align="center">Orbit Safe Claw</h1>

<p align="center">
  <strong>在浏览器中统一操控本地 Codex、Claude 与 Pi 的多工作区 AI 开发控制台。</strong>
</p>

<p align="center">
  Chat · Files · Git · Terminal · Debug · Plugins · Multi-agent Cluster
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest">下载最新版</a> ·
  <a href="#功能导览">功能导览</a> ·
  <a href="#高级配置">高级配置</a> ·
  <a href="https://github.com/Augustusjk2008/telegram-cli-bot/issues">反馈问题</a>
</p>

<p align="center">
  <a href="https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest"><img src="https://img.shields.io/github/v/release/Augustusjk2008/telegram-cli-bot?display_name=tag&amp;sort=semver&amp;style=flat-square&amp;color=5865f2" alt="Latest Release"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-20b8cd?style=flat-square" alt="Supported Platforms">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/self--hosted-local--first-16a085?style=flat-square" alt="Self-hosted and local-first">
</p>

> [!NOTE]
> Orbit Safe Claw 不托管模型，也不替代 Codex、Claude 或 Pi。它把本机 AI CLI、工作区和开发工具接入一个可远程访问的 Web 工作台，让多个仓库、Bot、会话和子 Agent 更容易统一管理。

## 一眼看懂

```mermaid
flowchart LR
    Browser["🖥️ 浏览器 / 移动端"] --> Orbit["Orbit Safe Claw"]
    Orbit --> Agents["🤖 Codex · Claude · Pi"]
    Orbit --> Workbench["💻 Chat · Files · Git · Terminal · Debug"]
    Orbit --> Cluster["🧭 子 Agent · Cluster"]
    Orbit --> Extend["🧩 Plugins · LiteLLM · Admin"]

    classDef orbit fill:#11162c,stroke:#49d8ff,color:#ffffff,stroke-width:2px;
    classDef node fill:#f5f8ff,stroke:#6a79ff,color:#172033;
    class Orbit orbit;
    class Browser,Agents,Workbench,Cluster,Extend node;
```

<table>
  <tr>
    <td width="33%" valign="top"><strong>🤖 多 Bot 与多会话</strong><br><br>每个 Bot 绑定自己的 CLI、工作目录、执行模式和会话；不同用户与 Agent 作用域相互隔离。</td>
    <td width="33%" valign="top"><strong>🧰 一体化开发工作台</strong><br><br>在同一页面完成聊天、文件编辑、Git、终端、调试和插件预览，减少窗口与上下文切换。</td>
    <td width="33%" valign="top"><strong>🧭 子 Agent 与集群</strong><br><br>通过子 Agent、路由和集群模式拆分审查、实现与验证任务，并统一回收结果。</td>
  </tr>
  <tr>
    <td valign="top"><strong>⚡ CLI 与原生执行</strong><br><br>Codex、Claude 使用普通 CLI 流；Pi 原生 Agent 使用 AG-UI，保留工具调用、权限请求和上下文用量。</td>
    <td valign="top"><strong>🧩 可扩展插件运行时</strong><br><br>通过 <code>plugin.json</code> 扩展文件视图、配置页和后台进程，支持重型 session 视图。</td>
    <td valign="top"><strong>🔒 本地优先、自主管理</strong><br><br>工作区、会话、配置和运行数据保留在自己的设备上，并提供用户权限、公告和更新管理。</td>
  </tr>
</table>

## 快速开始

### Windows：推荐使用绿色版

> [!TIP]
> Windows 绿色版内置 Python、Node.js、Git、Pi CLI、Pi 扩展和前端产物；解压即可启动。它不内置 Codex 或 Claude CLI，如需使用请先在本机安装对应 CLI。

1. 打开 [GitHub Releases](https://github.com/Augustusjk2008/telegram-cli-bot/releases/latest)。
2. 下载 `orbit-safe-claw-windows-x64-<version>.zip` 并解压到可写目录。
3. 双击 `start.bat`，或在终端执行：

   ```powershell
   .\start.bat
   ```

4. 按控制台输出打开 Web 地址。默认地址为 `http://127.0.0.1:8765`，登录口令保存在 `.env` 的 `WEB_API_TOKEN`。

需要传统安装流程时，下载 `orbit-safe-claw-windows-x64-installer-<version>.zip`，解压后运行 `install.bat`。

### Linux / macOS

| 平台 | 安装方式 |
|---|---|
| Linux x64 | 下载 `orbit-safe-claw-linux-x64-<version>.tar.gz`，解压后运行 `bash install.sh` |
| macOS | 下载 `orbit-safe-claw-macos-universal-<version>.tar.gz`，解压后运行 `bash install.sh` |

推荐解压到独立目录：

```bash
mkdir orbit-safe-claw
tar -xzf orbit-safe-claw-<platform>-<version>.tar.gz -C orbit-safe-claw
cd orbit-safe-claw
bash install.sh
bash start.sh
```

Linux/macOS 需要 Python 3.10+、Node.js 18+ 和 Git；Pi 原生 Agent 需要 Node.js 22+ 和 bash。

<details>
<summary><strong>从源码快照安装</strong></summary>

Windows：

```powershell
$zip="$env:TEMP\orbit-safe-claw.zip"
Invoke-WebRequest "https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.zip" -OutFile $zip
Expand-Archive $zip -DestinationPath . -Force
Set-Location .\telegram-cli-bot-master
.\install.bat
```

Linux/macOS：

```bash
curl -L https://github.com/Augustusjk2008/telegram-cli-bot/archive/refs/heads/master.tar.gz \
  | tar -xz
cd telegram-cli-bot-master
bash install.sh
```

</details>

## 功能导览

### 多工作区 Agent 控制

- 主 Bot 与托管 Bot 可绑定不同仓库、CLI 和工作目录。
- Web session 按用户、Bot 和 Agent 隔离，避免多工作区会话串线。
- Codex 与 Claude 普通 CLI 保留流式正文、状态、trace 和完成态。
- Pi 原生 Agent 保留 session、工具调用、权限请求、上下文用量和过程详情。

### Desktop Workbench

- **Chat**：普通 CLI 与原生 Agent 对话、历史恢复、过程详情和上下文状态。
- **Files**：文件树、编辑器、预览、多标签和语言服务导航。
- **Git**：状态、diff、提交历史与工作区操作。
- **Terminal**：持久化多标签 Web 终端，每个标签使用独立 shell 和 owner。
- **Debug**：面向 Python、C/C++、Godot 和通用 DAP 的调试入口。
- **Plugins**：PDF、DOCX、PPTX、CSV、Vivado waveform 等可扩展视图。

### 子 Agent 与集群协作

- CLI Bot 支持子 Agent、`@agent_id` 路由、集群模板和模型档位。
- 集群工具覆盖任务创建、状态查询、轮询和消息等待。
- 非集群聊天只绑定一个 active Agent；集群模式按明确路由分发子任务。

### 管理与扩展

- Admin Center 管理用户权限、邀请码、公告、更新和运行状态。
- 可选 LiteLLM 网关提供模型别名、多上游路由和 OpenAI 兼容接口。
- Codex CLI 用量统计可按本地自然日、Provider 和模型聚合展示。
- Cloudflare quick tunnel 和固定公网转发可用于受控的移动端访问。

## 支持矩阵

### 发布包

| 发布包 | 适用场景 | 运行时 |
|---|---|---|
| Windows 绿色版 | 最快体验、离线携带 | 内置 Python、Node.js、Git、Pi CLI 与前端产物 |
| Windows 安装版 | 常规本机安装 | 由安装脚本检查并准备依赖 |
| Linux x64 | Linux 自托管 | 使用本机 Python、Node.js、Git |
| macOS universal | macOS 源码包 | 使用本机 Python、Node.js、Git |

### 执行模式

| 模式 | 主要目标 | 传输与展示 |
|---|---|---|
| `cli` | Codex、Claude | Legacy SSE：正文、状态、trace、完成态 |
| `native_agent` | Pi | AG-UI：工具、权限、过程、上下文和原生 session |
| Cluster | 按 Bot/Agent 配置 | 子任务路由、轮询、消息回告和模型档位 |

## 安全边界

> [!WARNING]
> Orbit Safe Claw 可以读写工作区、执行终端命令并操作 Git。不要把未加保护的实例直接暴露到公网。

- 为 `WEB_API_TOKEN` 使用高强度随机值，并限制管理员账号权限。
- 公网访问应经过可信反向代理、防火墙和 TLS；反向代理必须支持 WebSocket。
- `.env`、真实 `managed_bots.json` 和 `~/.tcb/` 运行数据不得提交到仓库。
- 建议将 `TCB_DATA_DIR` 放在工作区之外，避免 workspace rollback 影响运行状态。
- 终端标签关闭时会终止对应 shell；Web 服务重启后，旧后台终端会话不会继续保留。

## 基本配置

首次安装后至少确认：

```env
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=C:\Users\YourName\project
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=<高强度随机口令>
```

运行态数据默认位于 `~/.tcb/orbit-safe-claw`，可通过 `TCB_DATA_DIR` 覆盖。

<details>
<summary><strong>托管多个 Bot</strong></summary>

参考 `managed_bots.example.json` 创建本地 `managed_bots.json`：

```json
{
  "bots": [
    {
      "alias": "repo2",
      "cli_type": "codex",
      "cli_path": "codex",
      "working_dir": "C:/work/repo2",
      "enabled": true
    }
  ]
}
```

</details>

## 高级配置

<details>
<summary><strong>固定公网地址与 frp 反向代理</strong></summary>

固定 IP 服务器可通过 frp 转发内网机器。每台机器必须使用独立节点路径，并完整保留 `/node/<节点 ID>/` 前缀：

```text
http://<固定IP>:18088/node/<节点ID>/
```

本机 `.env`：

```env
TCB_NODE_ID=my-laptop
WEB_BASE_PATH=/node/my-laptop
WEB_PUBLIC_URL=http://<固定IP>:18088/node/my-laptop
WEB_FIXED_PUBLIC_FORWARD_ENABLED=true
WEB_FIXED_PUBLIC_FORWARD_URL=http://<固定IP>:18088/node/my-laptop
TCB_HUB_FRPS_PORT=7000
TCB_HUB_FRPS_TOKEN=<frps-token>
TCB_HUB_NODE_TOKEN=<random-node-token>
TCB_HUB_FRPC_PATH=frpc
TCB_HUB_FRPC_AUTOSTART=true
```

固定 IP 服务器的 `frps.toml`：

```toml
bindPort = 7000
vhostHTTPPort = 18765
auth.token = "<frps-token>"
```

Nginx 必须保留节点路径并支持 WebSocket：

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

公网服务器需放通 `18088`、`7000`。`WEB_BASE_PATH` 必须与反代路径完全一致；修改路径后重新构建前端并重启 Web。

</details>

<details>
<summary><strong>非绿色版安装 Pi 原生 Agent</strong></summary>

非绿色版依赖 Node.js 22+、Git 和 bash。安装固定版本：

```bash
npm install -g @earendil-works/pi-coding-agent@0.74.2 pi-workspace-history@0.2.2
```

至少配置：

```env
NATIVE_AGENT_ENABLED=true
NATIVE_AGENT_PI_COMMAND=pi
```

Pi 扩展默认位于 `~/.pi/agent/extensions`。使用 `PI_AGENT_SETTINGS` 或 `NATIVE_AGENT_PI_HOME` 时，应把 `workspace-history.ts` 和仓库内 `bot/cluster/pi_extension/tcb-cluster.ts` 放入实际生效的 extensions 目录。Windows 的 Pi `shellPath` 应指向 Git Bash。

Pi session 由工作目录、模型、Pi Agent 和推理强度共同绑定；任一项变化都会创建新的 session 与 workspace-history rollback 链。

</details>

<details>
<summary><strong>可选 LiteLLM 网关</strong></summary>

LiteLLM 网关不是普通 CLI 的必经链路；关闭时，Codex 和 Claude 继续直连自己的 Provider。

每条路由可设置模型别名、LiteLLM model、上游地址、密钥、额外参数，以及 `auto`、`chat_completions`、`responses` 三种 endpoint 模式。保存后会热切换，不需要重启主 Web 服务；状态接口不会回显上游密钥。

配置与日志默认位于 `~/.tcb/orbit-safe-claw/transfer`。

</details>

<details>
<summary><strong>Codex CLI 用量统计</strong></summary>

管理中心可即时开启或关闭采集。功能默认关闭，只统计启用后由 Orbit 启动的普通 Codex CLI 进程，不回填历史，也不统计 Claude、Pi、原生 Agent、LiteLLM Transfer、行内补全或手工终端进程。

统计按日期、Provider 和模型聚合，数据默认保存在 `~/.tcb/orbit-safe-claw/codex-usage/usage.sqlite3`，不会保存逐轮提示词、认证头或 API 密钥。

</details>

<details>
<summary><strong>指定 Web 终端 Shell</strong></summary>

```env
WEB_TERMINAL_SHELL_PATH=/usr/bin/zsh
```

Windows 示例：

```env
WEB_TERMINAL_SHELL_PATH=C:\Program Files\PowerShell\7\pwsh.exe
```

该配置只影响 Web xterm 内运行的 shell，不会启动外部 GUI 终端窗口。

</details>

## 更新

设置页和 Admin Center 会从 GitHub Releases 检查、下载更新。下载完成后，更新在下次启动或重启时应用。

首次安装生成的 `.env` 默认包含：

```env
APP_UPDATE_REPOSITORY=Augustusjk2008/telegram-cli-bot
```

使用自己的 Release 仓库时，将其改成对应的 `owner/repo`。

## 项目结构

```text
.
├─ bot/                    # Python 后端、Web API、Bot、Native Agent、Plugins
├─ front/                  # React/Vite 工作台前端
├─ examples/plugins/       # 示例插件与文件预览器
├─ tests/                  # 后端与集成测试
├─ scripts/                # 安装、构建和辅助脚本
├─ deploy/                 # 部署相关文件
├─ install.*               # 安装入口
├─ start.*                 # 启动入口
├─ managed_bots.example.json
└─ AGENTS.md               # Coding Agent 工作约定
```

本地运行文件包括 `.env`、`managed_bots.json`、`front/dist/` 和 `~/.tcb/orbit-safe-claw`；不要提交真实配置或运行数据。

## 开发与验证

```bash
# 后端
python -m bot
python -m pytest tests -q

# 前端
cd front
npm run test:gate
npm run lint
npm run build
```

项目以 Windows 为优先平台，同时维护 Linux/macOS 安装与启动脚本。涉及布局的改动应补充浏览器级检查；涉及发布包时应运行后端测试、前端门禁、lint 和生产构建。

## 获取帮助

- 下载与版本：[GitHub Releases](https://github.com/Augustusjk2008/telegram-cli-bot/releases)
- Bug 与功能建议：[GitHub Issues](https://github.com/Augustusjk2008/telegram-cli-bot/issues)
- 配置示例：`.env.example`、`managed_bots.example.json`
- 测试约定：`docs/testing-policy.md`

如果这个项目对你有帮助，欢迎点一个 Star，或通过 Issue 分享你的使用场景。
