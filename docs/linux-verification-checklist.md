# Linux 验证清单

本文件用于记录 Linux 支持改造后的验证步骤。

## 一、当前在 Windows 上已经能验证的内容

虽然现在没有真实 Linux 运行环境，但以下内容已经通过自动化测试或构建验证：

### 1. 后端平台抽象

已验证：

- Linux 默认 shell 选择为 `bash`
- Linux 下 CLI 可执行文件解析不会错误追加 Windows 扩展名
- Linux 路径显示截断逻辑可工作
- Linux 进程组参数会使用 `start_new_session=True`

对应测试覆盖：

- `tests/test_platform_support.py`
- `tests/test_cli.py`
- `tests/test_platform_processes.py`

### 2. 旧 `webcli` 退场

已验证：

- 运行时只保留 `cli` / `assistant`
- 旧保存的 `webcli` bot 会自动迁移成 `cli`
- 迁移结果会回写到配置文件

对应测试覆盖：

- `tests/test_assistant.py`

### 3. Linux 脚本分发

已验证：

- Linux 下系统脚本只识别 `.sh` / `.py`
- `.sh` 脚本执行会通过 `bash <script>` 启动

对应测试覆盖：

- `tests/test_handlers/test_admin.py`

### 4. Tunnel 启动参数

已验证：

- `TunnelService.start()` 会把平台进程组选项透传给 `subprocess.Popen`

对应测试覆盖：

- `tests/test_tunnel_service.py`

### 5. 前端跨平台行为

已验证：

- 路径输入不再强行套 Windows 规则
- 终端连接默认发送 `shell: "auto"`
- Bot 创建流程可保留 Linux 风格路径
- 前端完整测试通过
- 前端生产构建通过

对应测试覆盖：

- `front/src/test/path-input.test.ts`
- `front/src/test/terminal-screen.test.tsx`
- `front/src/test/app.test.tsx`

### 6. Linux 启动脚本存在性

已验证：

- `start.sh` 已存在
- 含 `TELEGRAM_CLI_BRIDGE_SUPERVISOR=1`
- 支持 `web` 模式切换

对应测试覆盖：

- `tests/test_start_scripts.py`

### 7. 当前仍然无法在 Windows 上替代 Linux 实测的部分

还没有真实验证：

- `bash start.sh` 在真实 Ubuntu/Debian 上的运行结果
- Linux PTY 行为与 Web 终端实际交互
- systemd 托管效果
- Linux 下真实 `cloudflared` 安装与启动
- Quick Tunnel / Named Tunnel 的真实连通性
- Linux 文件权限与执行权限问题

## 二、Linux 环境就绪后的推荐验证顺序

建议使用 Ubuntu 22.04/24.04 或 Debian 12。

### 阶段 A：基础环境

1. 安装基础依赖

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-pip python-is-python3 nodejs npm
```

2. 可选：安装 `cloudflared`

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update
sudo apt-get install -y cloudflared
cloudflared --version
```

3. 拉代码并安装依赖

```bash
git clone <repo-url> telegram_cli_bridge
cd telegram_cli_bridge/refactoring
python -m pip install -r requirements.txt
cd front
npm install
cd ..
```

### 阶段 B：本地自动化验证

4. 跑后端测试

```bash
python -m pytest tests -q
```

预期：

- 全部通过

5. 跑前端测试与构建

```bash
cd front
npm test
npm run build
cd ..
```

预期：

- `vitest` 通过
- `vite build` 成功

### 阶段 C：最小运行验证

6. 创建 `.env`

推荐最小示例：

```env
TELEGRAM_ENABLED=false
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=dev-token

CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=/srv/telegram-cli-bridge/demo

WEB_TUNNEL_MODE=disabled
WEB_PUBLIC_URL=
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

7. 准备工作目录

```bash
sudo mkdir -p /srv/telegram-cli-bridge/demo
sudo chown -R "$USER":"$USER" /srv/telegram-cli-bridge
```

8. 给 Linux 启动脚本执行权限

```bash
chmod +x start.sh
chmod +x scripts/build_web_frontend.sh
```

9. 启动纯 Web 模式

```bash
bash start.sh web
```

预期：

- 进程能启动
- 控制台显示 Web API 已开启
- 无 `powershell` / `.cmd` 相关错误

10. 浏览器访问

```text
http://127.0.0.1:8765
```

预期：

- 能打开登录页
- 使用 `WEB_API_TOKEN` 登录成功

### 阶段 D：Web 功能检查

11. 检查终端页

验证项：

- 终端能打开
- 默认 shell 实际为 `bash`
- 能执行 `pwd`
- 能执行 `ls`

建议手工输入：

```bash
pwd
ls
echo $SHELL
```

12. 检查 Bot 管理页

创建一个测试 Bot：

- alias: `team-linux`
- CLI path: `codex`
- working dir: `/srv/telegram-cli-bridge/team-linux`

预期：

- 可成功创建
- 创建后路径保持 Linux 样式
- 不会被改写成 Windows 形式

13. 检查系统脚本页

预期：

- `build_web_frontend.sh` 可见
- 不会出现 Windows 专用 `.ps1` / `.bat` 脚本

执行“重建前端”后预期：

- 实际通过 `bash scripts/build_web_frontend.sh` 运行
- 日志能正常返回到前端

### 阶段 E：CLI 实际联通

14. 验证本机 CLI 命令可直接运行

例如：

```bash
codex --help
claude --help
kimi --help
```

至少确认你真正要用的那个 CLI 是通的。

15. 在 Web Chat 或 Telegram 中发一条最小消息

建议：

```text
请输出当前工作目录，并列出当前目录文件
```

预期：

- 返回正常
- 会话能继续
- `/reset`、`/kill` 等基本命令可用

### 阶段 F：Quick Tunnel 可选验证

16. 如果只想验证 quick tunnel 是否能拉起

`.env` 改为：

```env
WEB_TUNNEL_MODE=cloudflare_quick
WEB_TUNNEL_AUTOSTART=true
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

启动后检查：

- Web 设置页能显示 `trycloudflare.com` 地址
- 外网手机可打开页面

但这里必须接受一个已知限制：

- `trycloudflare.com` quick tunnel 不支持 SSE
- 所以 Web chat 流式回复不应作为 quick tunnel 的正式验收项

结论：

- quick tunnel 只验“能否临时暴露页面”
- 不验“是否适合生产流式聊天”

### 阶段 G：Named Tunnel 正式验证

17. 创建 named tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create telegram-cli-bridge
```

18. 写 `/home/<user>/.cloudflared/config.yml`

示例：

```yaml
tunnel: <TUNNEL-UUID>
credentials-file: /home/<user>/.cloudflared/<TUNNEL-UUID>.json
ingress:
  - hostname: bot.example.com
    service: http://127.0.0.1:8765
  - service: http_status:404
```

19. 安装 cloudflared 系统服务

```bash
sudo cloudflared --config /home/<user>/.cloudflared/config.yml service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

注意：

- 必须显式带 `--config /home/<user>/.cloudflared/config.yml`
- 因为 `sudo` 会把 `$HOME` 切到 `/root`

20. 应用侧配置改为：

```env
WEB_TUNNEL_MODE=disabled
WEB_PUBLIC_URL=https://bot.example.com
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

21. 验证公网访问

预期：

- `https://bot.example.com` 可打开
- Web 登录、聊天、文件、Git、终端可用
- 流式聊天正常

### 阶段 H：systemd 托管验证

22. 安装应用 systemd 服务

```bash
sudo cp deploy/systemd/telegram-cli-bridge.service /etc/systemd/system/telegram-cli-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-cli-bridge
sudo systemctl status telegram-cli-bridge
```

如果路径不同，先修改 unit 文件中的：

- `User`
- `Group`
- `WorkingDirectory`
- `ExecStart`

23. 重启验证

```bash
sudo systemctl restart telegram-cli-bridge
sudo systemctl status telegram-cli-bridge
journalctl -u telegram-cli-bridge -n 100 --no-pager
```

预期：

- 服务能自动拉起
- 无循环崩溃
- 日志里没有 `powershell`、`.cmd`、Windows 路径假设

## 三、最终验收结论建议

Linux 环境准备好后，建议按下面标准给结果：

### 可判定为“基础可用”

满足以下全部条件：

- 后端测试通过
- 前端测试通过
- 前端构建通过
- `bash start.sh web` 能启动
- Web 登录 / Chat / Files / Terminal / Settings 可用
- Linux 路径可正常创建 Bot 与切换目录

### 可判定为“正式部署可用”

在“基础可用”之外，再满足：

- 指定 CLI 在 Linux 上能稳定工作
- Named Tunnel 正常
- systemd 正常
- 机器重启后服务可恢复
- 远程公网访问下流式聊天可用
