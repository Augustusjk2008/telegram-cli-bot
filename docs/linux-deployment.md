# Linux 部署指南

本文档面向首批正式支持的平台：

- Ubuntu
- Debian

目标是让项目在 Linux 上同时保留两种运行方式：

- `bash start.sh` 手动常驻启动
- `systemd` 托管后台服务

## 1. 依赖准备

建议先准备：

- Python 3.10 及以上
- Node.js 18 及以上
- Git
- 至少一个本地 AI CLI：`codex` / `claude` / `kimi`
- 可选：`cloudflared`

如果你的系统里没有 `python` 命令，而只有 `python3`，请先安装 `python-is-python3`，或者自行调整 `start.sh` / systemd 配置中的 Python 命令。

## 2. 拉取项目并安装依赖

```bash
git clone <your-repo-url> /opt/telegram-cli-bridge
cd /opt/telegram-cli-bridge
python -m pip install -r requirements.txt
```

如果要启用 Web：

```bash
cd /opt/telegram-cli-bridge/front
npm install
npm run build
```

## 3. 创建 `.env`

```bash
cd /opt/telegram-cli-bridge
cp .env.example .env
```

一个 Linux 常见示例：

```env
TELEGRAM_BOT_TOKEN=
ALLOWED_USER_IDS=123456789

CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=/srv/telegram-cli-bridge/project

TELEGRAM_ENABLED=true
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=change-this-password

WEB_TUNNEL_MODE=disabled
WEB_PUBLIC_URL=
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

说明：

- 如果 CLI 已在 `PATH` 中，`CLI_PATH` 直接填命令名即可
- 如果只跑 Web，把 `TELEGRAM_ENABLED=false`
- 如果 Cloudflare Tunnel 由系统级 named tunnel 独立托管，应用侧推荐 `WEB_TUNNEL_MODE=disabled`

## 4. 手动启动

默认模式：

```bash
cd /opt/telegram-cli-bridge
bash start.sh
```

纯 Web 模式：

```bash
cd /opt/telegram-cli-bridge
bash start.sh web
```

`start.sh` 会设置 `TELEGRAM_CLI_BRIDGE_SUPERVISOR=1`，并在进程请求重启时自动拉起下一轮 `python -m bot`。

## 5. systemd 托管

仓库已提供模板：

- `deploy/systemd/telegram-cli-bridge.service`

推荐步骤：

```bash
sudo useradd --system --create-home --home-dir /opt/telegram-cli-bridge telegram-cli-bridge || true
sudo chown -R telegram-cli-bridge:telegram-cli-bridge /opt/telegram-cli-bridge
sudo chmod +x /opt/telegram-cli-bridge/start.sh
sudo cp deploy/systemd/telegram-cli-bridge.service /etc/systemd/system/telegram-cli-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-cli-bridge
sudo systemctl status telegram-cli-bridge
```

如果你的部署目录或运行用户不是：

- `/opt/telegram-cli-bridge`
- `telegram-cli-bridge`

请先编辑 unit 文件中的：

- `User`
- `Group`
- `WorkingDirectory`
- `ExecStart`

## 6. Linux 上安装 `cloudflared`

Ubuntu / Debian 推荐直接用 Cloudflare 官方 APT 仓库：

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update
sudo apt-get install cloudflared
cloudflared --version
```

安装完成后，通常把 `.env` 中的路径写成：

```env
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

如果 `cloudflared` 已在 `PATH` 中，也可以留空。

## 7. Quick Tunnel：只用于调试

项目内置的 quick tunnel 模式会调用：

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

对应配置：

```env
WEB_TUNNEL_MODE=cloudflare_quick
WEB_TUNNEL_AUTOSTART=true
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

但 Linux 文档里必须明确把它当作临时方案：

- Quick Tunnel 只适合开发调试，不适合生产
- `trycloudflare.com` quick tunnel 不支持 SSE
- 本项目 Web chat 的流式回复依赖 SSE，所以 quick tunnel 不适合作为正式公网入口

换句话说：

- 你可以用 quick tunnel 临时从手机打开页面
- 但不要把它当成长期稳定的公网地址

## 8. Named Tunnel：正式环境推荐

正式环境推荐把 Cloudflare Tunnel 作为独立系统服务运行，而不是让应用自己拉 quick tunnel。

### 8.1 创建 named tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create telegram-cli-bridge
```

### 8.2 编写配置文件

`/home/<user>/.cloudflared/config.yml`

```yaml
tunnel: <TUNNEL-UUID>
credentials-file: /home/<user>/.cloudflared/<TUNNEL-UUID>.json
ingress:
  - hostname: bot.example.com
    service: http://127.0.0.1:8765
  - service: http_status:404
```

### 8.3 安装为系统服务

```bash
sudo cloudflared --config /home/<user>/.cloudflared/config.yml service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
sudo systemctl status cloudflared
```

这里一定要显式写：

```bash
--config /home/<user>/.cloudflared/config.yml
```

原因是：

- `sudo` 会把 `$HOME` 切到 `/root`
- 不显式传 `--config` 时，`service install` 很容易去错误的 home 目录找配置

### 8.4 应用侧推荐配置

如果 named tunnel 已经由系统独立托管，应用侧建议：

```env
WEB_TUNNEL_MODE=disabled
WEB_PUBLIC_URL=https://bot.example.com
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

这样应用只负责展示公网地址，不再自己启动 quick tunnel。

## 9. 验证清单

部署完成后，至少确认：

- `python -m pytest tests/test_tunnel_service.py -q` 能通过
- `bash start.sh` 可以正常启动
- `systemctl status telegram-cli-bridge` 为 `active`
- Web 页面能通过 `http://127.0.0.1:8765` 打开
- 如果用了 named tunnel，`https://bot.example.com` 可以稳定访问

## 10. 参考资料

- Cloudflare local management / create local tunnel
- Cloudflare Linux service install
- Cloudflare TryCloudflare 限制说明

具体官方页面：

- <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/>
- <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/linux/>
- <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/>
