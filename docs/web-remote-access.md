# Web 异地访问指南

本文档给出这个仓库的 Web 远程访问最终方案，并保留两种可切换的入口模式：

- 推荐长期使用：`Tailscale Personal + Tailscale Serve`
- 保留临时调试：`Cloudflare Quick Tunnel`

目标：

- 网络环境经常变化时仍可访问
- 同时支持 Windows 和 Linux
- 通过 `.env` 配置切换，不改代码

## 1. 最终建议

默认使用 Tailscale。

原因：

- 不依赖固定公网 IP
- 不需要 DDNS
- 不需要路由器端口映射
- 只在你的 tailnet 内开放，不把管理面板直接暴露到公网
- 对中国大陆个人自用场景，通常比 `trycloudflare.com` Quick Tunnel 更稳、更快

Cloudflare Quick Tunnel 只保留为应急/调试入口。

原因：

- 当前仓库内置的是 `cloudflare_quick`
- `trycloudflare.com` Quick Tunnel 不支持 SSE
- 本项目 Web chat 的流式回复依赖 SSE
- 因此 Quick Tunnel 不适合作为长期主入口

## 2. 配置切换规则

本项目 Web 相关配置在：

- [`.env.example`](C:/Users/JiangKai/telegram_cli_bridge/refactoring/.env.example)
- [`bot/config.py`](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/config.py)

切换规则如下。

### 2.1 Tailscale 方案

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password

WEB_TUNNEL_MODE=disabled
WEB_TUNNEL_AUTOSTART=true
WEB_PUBLIC_URL=https://your-device.your-tailnet.ts.net
WEB_TUNNEL_CLOUDFLARED_PATH=
```

说明：

- `WEB_TUNNEL_MODE=disabled` 表示应用不再自己启动 `cloudflared`
- `WEB_PUBLIC_URL` 不是必须，但建议填写，这样 Web 设置页能直接显示你的 Tailscale 地址
- `WEB_HOST` 保持 `127.0.0.1` 即可，不需要改成 `0.0.0.0`

### 2.2 Cloudflare Quick Tunnel 方案

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password

WEB_TUNNEL_MODE=cloudflare_quick
WEB_TUNNEL_AUTOSTART=true
WEB_PUBLIC_URL=
WEB_TUNNEL_CLOUDFLARED_PATH=/path/to/cloudflared
```

说明：

- 使用 Quick Tunnel 时，`WEB_PUBLIC_URL` 必须留空
- 只要 `WEB_PUBLIC_URL` 非空，应用就会进入手工公网地址模式，不会自动启动 quick tunnel
- Windows 示例路径：
  `WEB_TUNNEL_CLOUDFLARED_PATH=C:\Tools\cloudflared\cloudflared.exe`
- Linux 示例路径：
  `WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared`

## 3. 通用准备步骤

无论使用哪种方案，先完成这些准备。

### 3.1 安装项目依赖

Windows / Linux 通用：

```bash
python -m pip install -r requirements.txt
```

首次启用 Web 前端：

```bash
cd front
npm install
npm run build
```

### 3.2 配置 `.env`

可以从示例文件开始：

```bash
cp .env.example .env
```

Windows PowerShell 也可以直接复制文件。

至少确认这些项：

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=改成你自己的网页登录口令
```

建议同时确认：

- `ALLOWED_USER_IDS` 只保留你自己的 Telegram 用户 ID
- `WEB_API_TOKEN` 使用强口令
- 如果你只想跑 Web，不跑 Telegram，设置 `TELEGRAM_ENABLED=false`

### 3.3 启动方式

只跑 Web：

Windows：

```powershell
.\start.bat web
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 web
```

Linux：

```bash
bash start.sh web
```

同时跑 Telegram 和 Web：

Windows：

```powershell
.\start.bat
```

Linux：

```bash
bash start.sh
```

### 3.4 先验证本地 Web

启动后先在本机验证：

```text
http://127.0.0.1:8765
```

也可以检查健康接口：

```bash
curl http://127.0.0.1:8765/api/health
```

确认本地正常后，再继续做远程入口。

## 4. 方案 A：Tailscale Personal + Tailscale Serve

这是推荐的长期方案。

### 4.1 方案特点

- 适合“我自己跨设备远程访问”
- 访问设备和被访问设备都要登录同一个 Tailscale 网络
- 不提供公开互联网 URL
- 默认只在 tailnet 内可见

### 4.2 Windows 准备步骤

1. 从 Tailscale 官方页面下载安装 Windows 客户端。
2. 安装完成后，右下角托盘会出现 Tailscale 图标。
3. 右键图标，执行登录。
4. 确认当前设备已经出现在你的 tailnet 中。

安装完成后，可以在 PowerShell 中检查：

```powershell
tailscale ip
tailscale status
```

后续执行 `tailscale serve` 时，建议使用“以管理员身份运行”的 PowerShell。

### 4.3 Linux 准备步骤

Ubuntu / Debian / 常见 Linux 发行版可直接使用官方安装脚本：

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

首次执行 `sudo tailscale up` 时，终端会输出一个登录链接；在浏览器中完成登录即可。

安装后检查：

```bash
tailscale ip
tailscale status
```

如果这台机器是长期在线的远程节点，可以在 Tailscale 后台考虑关闭这台设备的 key expiry；这是可选项，安全性会略有下降，但能减少定期重新登录。

### 4.4 应用侧配置

把 `.env` 调整为：

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password

WEB_TUNNEL_MODE=disabled
WEB_TUNNEL_AUTOSTART=true
WEB_PUBLIC_URL=https://your-device.your-tailnet.ts.net
WEB_TUNNEL_CLOUDFLARED_PATH=
```

其中：

- `your-device.your-tailnet.ts.net` 替换成实际的 Serve 地址
- 如果你暂时还不知道最终地址，可以先把 `WEB_PUBLIC_URL=` 留空，等 Serve 跑起来后再回填

### 4.5 启用 Tailscale Serve

本项目 Web 默认监听 `127.0.0.1:8765`，正好适合 Serve 代理。

在 Web 服务已经启动的前提下：

Windows：

```powershell
tailscale serve --bg 8765
tailscale serve status
```

Linux：

```bash
sudo tailscale serve --bg 8765
tailscale serve status
```

说明：

- `--bg` 会让 Serve 在后台持续生效
- Tailscale 重启或机器重启后，后台 Serve 配置会自动恢复
- 如果命令提示需要启用 HTTPS，按提示在浏览器里授权即可

### 4.6 获取访问地址

成功后，命令输出里会显示类似：

```text
https://your-device.your-tailnet.ts.net
```

你也可以通过：

```bash
tailscale serve status
```

再次查看。

把这个地址填回 `.env`：

```env
WEB_PUBLIC_URL=https://your-device.your-tailnet.ts.net
```

然后重启应用。这样项目的 Web 设置页也会显示当前远程访问地址。

### 4.7 远程访问步骤

在你的另一台设备上：

1. 安装 Tailscale
2. 登录同一个 tailnet
3. 打开 `https://your-device.your-tailnet.ts.net`
4. 输入 `WEB_API_TOKEN`

### 4.8 验证清单

- 本机可以访问 `http://127.0.0.1:8765`
- `tailscale status` 显示当前设备在线
- `tailscale serve status` 显示当前 HTTPS 入口已代理到 `127.0.0.1:8765`
- 另一台已登录同一 tailnet 的设备能打开 `https://your-device.your-tailnet.ts.net`
- Web 聊天流式输出正常，不再受 Quick Tunnel 的 SSE 限制

### 4.9 停用或重置 Serve

如果要停止共享：

```bash
tailscale serve off
```

Linux 如果之前用 `sudo tailscale serve --bg 8765` 启用过，这里也用 `sudo tailscale serve off`。

如果要重新配置：

```bash
tailscale serve reset
tailscale serve --bg 8765
```

Linux 同理改为：

```bash
sudo tailscale serve reset
sudo tailscale serve --bg 8765
```

## 5. 方案 B：Cloudflare Quick Tunnel

这是保留方案，只建议：

- 临时调试
- Tailscale 暂时不可用时的应急访问
- 需要快速生成一个临时公网地址时

### 5.1 方案限制

- `trycloudflare.com` Quick Tunnel 不支持 SSE
- 本项目 Web chat 流式回复依赖 SSE
- 因此页面能打开，不代表聊天体验一定正常
- 中国大陆个人网络场景下，Quick Tunnel 往往比 Tailscale 更慢

### 5.2 Windows 准备步骤

1. 从 Cloudflare 官方下载页获取 `cloudflared.exe`
2. 放到固定目录，例如 `C:\Tools\cloudflared\cloudflared.exe`
3. 在 PowerShell 中验证：

```powershell
C:\Tools\cloudflared\cloudflared.exe --version
```

### 5.3 Linux 准备步骤

Ubuntu / Debian 可使用 Cloudflare 官方仓库：

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update
sudo apt-get install cloudflared
cloudflared --version
```

### 5.4 应用侧配置

Windows：

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password

WEB_TUNNEL_MODE=cloudflare_quick
WEB_TUNNEL_AUTOSTART=true
WEB_PUBLIC_URL=
WEB_TUNNEL_CLOUDFLARED_PATH=C:\Tools\cloudflared\cloudflared.exe
```

Linux：

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password

WEB_TUNNEL_MODE=cloudflare_quick
WEB_TUNNEL_AUTOSTART=true
WEB_PUBLIC_URL=
WEB_TUNNEL_CLOUDFLARED_PATH=/usr/bin/cloudflared
```

### 5.5 启动与访问

启动应用后，仓库内置的 TunnelService 会自动执行：

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

成功后：

- Web 设置页会显示 `https://*.trycloudflare.com`
- 在启用 Telegram 的情况下，主 bot 也可能把地址推送给允许用户
- 地址会复制到本机剪贴板

### 5.6 验证清单

- 本机可以访问 `http://127.0.0.1:8765`
- `cloudflared --version` 正常
- Web 设置页出现 `https://*.trycloudflare.com`
- 远程设备能打开页面
- 如果出现聊天流式卡顿、长时间无增量输出，这是 Quick Tunnel 的已知限制，不是当前推荐修复方向

## 6. 推荐切换流程

### 6.1 从 Cloudflare Quick Tunnel 切到 Tailscale

1. 安装并登录 Tailscale
2. 启动本地 Web，确认 `http://127.0.0.1:8765` 正常
3. 执行：

```bash
tailscale serve --bg 8765
```

4. 拿到 `https://your-device.your-tailnet.ts.net`
5. 修改 `.env`：

```env
WEB_TUNNEL_MODE=disabled
WEB_PUBLIC_URL=https://your-device.your-tailnet.ts.net
WEB_TUNNEL_CLOUDFLARED_PATH=
```

6. 重启应用

### 6.2 从 Tailscale 切回 Cloudflare Quick Tunnel

1. 关闭 Serve：

```bash
tailscale serve off
```

2. 修改 `.env`：

```env
WEB_TUNNEL_MODE=cloudflare_quick
WEB_TUNNEL_AUTOSTART=true
WEB_PUBLIC_URL=
WEB_TUNNEL_CLOUDFLARED_PATH=/path/to/cloudflared
```

3. 重启应用

## 7. 故障排查

### 7.1 Tailscale 方案下，远程打不开

优先检查：

- 两台设备是否登录同一个 tailnet
- `tailscale status` 是否在线
- `tailscale serve status` 是否仍然指向 `127.0.0.1:8765`
- 本机 `http://127.0.0.1:8765` 是否正常

### 7.2 Cloudflare 方案下，页面打开慢或聊天不流畅

优先检查：

- `/api/health` 的本地访问是否很快
- `trycloudflare.com` 访问是否明显慢于本地
- 是否遇到 SSE 不支持带来的流式问题

如果本地很快、Quick Tunnel 很慢，这属于链路和产品限制，不建议继续优化应用代码来硬扛。

### 7.3 为什么 Tailscale 模式还要保留 `WEB_PUBLIC_URL`

因为当前仓库的 Web 设置页可以展示“当前外部访问地址”。Tailscale 并不是由应用内部拉起的 tunnel，所以最简单的做法就是：

- `WEB_TUNNEL_MODE=disabled`
- `WEB_PUBLIC_URL=https://your-device.your-tailnet.ts.net`

这样应用只负责展示地址，不负责管理 Tailscale 生命周期。

## 8. 最终落地建议

如果你是个人自用，并且需要在不同地点访问自己的 Web bot，建议长期固定为：

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=change-this-password

WEB_TUNNEL_MODE=disabled
WEB_PUBLIC_URL=https://your-device.your-tailnet.ts.net
WEB_TUNNEL_CLOUDFLARED_PATH=
```

然后把 Cloudflare Quick Tunnel 保留为备用配置片段，只在临时调试时切回去。

## 9. 参考资料

- Tailscale Windows 安装：
  <https://tailscale.com/docs/install/windows>
- Tailscale Linux 安装：
  <https://tailscale.com/docs/install/linux>
- Tailscale Serve：
  <https://tailscale.com/docs/features/tailscale-serve>
- Tailscale `serve` CLI：
  <https://tailscale.com/docs/reference/tailscale-cli/serve>
- Tailscale 连接类型与直连/中继：
  <https://tailscale.com/docs/reference/connection-types>
- Tailscale 稳定地址说明：
  <https://tailscale.com/docs/concepts/tailscale-ip-addresses>
- Tailscale 免费个人计划：
  <https://tailscale.com/pricing>
- Cloudflare Quick Tunnel：
  <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/>
- Cloudflare `cloudflared` 下载：
  <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>
