"""Web CLI 模式处理器"""

import asyncio
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import NGROK_DIR, WORKING_DIR
from bot.handlers.tui_server import start_tui_server_background, stop_tui_server

# ngrok authtoken（从配置文件或环境变量读取）
NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN", "3Ac4HMGBAiQPpxvVhdHhDhbGMoF_ScrCA8sDTvR2n3xuvbRg")

logger = logging.getLogger(__name__)

# 全局变量存储 ngrok 进程和 URL
_ngrok_process: Optional[subprocess.Popen] = None
_ngrok_url: Optional[str] = None
_web_server_process: Optional[subprocess.Popen] = None
_ngrok_lock = threading.Lock()
_tui_mode: bool = False  # TUI 模式标志


def _kill_port_processes(port: int = 8080) -> tuple[bool, str]:
    """关闭所有监听指定端口的进程"""
    try:
        # 使用 PowerShell 查找并杀死占用端口的进程
        ps_script = f'''
        $connections = Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue
        if (-not $connections) {{
            Write-Output "NO_PROCESS"
            exit 0
        }}
        $killed = @()
        foreach ($conn in $connections) {{
            try {{
                $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
                if ($proc) {{
                    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
                    $killed += "$($conn.OwningProcess):$($proc.ProcessName)"
                }}
            }} catch {{}}
        }}
        if ($killed.Count -eq 0) {{
            Write-Output "NO_PROCESS"
        }} else {{
            Write-Output ($killed -join ',')
        }}
        '''
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout.strip()
        if output == "NO_PROCESS":
            return True, f"端口 {port} 未被占用"
        else:
            return True, f"已关闭端口 {port} 的进程: {output}"
    except subprocess.TimeoutExpired:
        return False, f"关闭端口 {port} 进程超时"
    except Exception as e:
        return False, f"关闭端口 {port} 进程失败: {e}"


def _start_web_server(port: int = 8080, tui_mode: bool = False, ws_port: int = 8081) -> subprocess.Popen:
    """启动简单的 web 服务器"""
    # 创建临时 HTML 文件
    html_dir = Path(__file__).parent.parent.parent / "bot" / "data" / "webcli"
    html_dir.mkdir(parents=True, exist_ok=True)

    html_file = html_dir / "index.html"

    if tui_mode:
        # TUI 模式：使用 xterm.js，自动连接 PowerShell
        # 注意：实际使用的是 tui_server.py 中的 HTML，这个只是备用
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PowerShell Web Terminal</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
    <style>
        body {{
            margin: 0;
            padding: 0;
            background: #0c0c0c;
            display: flex;
            flex-direction: column;
            height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        .header {{
            background: #1e1e1e;
            color: #cccccc;
            padding: 10px 20px;
            border-bottom: 1px solid #333;
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 14px;
            font-weight: 500;
        }}
        .status {{
            margin-left: auto;
            font-size: 12px;
            padding: 2px 8px;
            border-radius: 3px;
            background: #333;
        }}
        .status.connecting {{ color: #f9f1a5; }}
        .status.connected {{ color: #16c60c; background: #0d3b0d; }}
        .status.disconnected {{ color: #e74856; }}
        #terminal-container {{
            flex: 1;
            overflow: hidden;
        }}
        #terminal {{
            width: 100%;
            height: 100%;
            padding: 5px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🖥️ PowerShell Web Terminal</h1>
        <span class="status connecting" id="status">连接中...</span>
    </div>
    <div id="terminal-container">
        <div id="terminal"></div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
    <script>
        // 初始化 xterm.js
        const term = new Terminal({{
            cursorBlink: true,
            fontSize: 14,
            fontFamily: '"Cascadia Code", "Courier New", "Consolas", monospace',
            theme: {{
                background: '#0c0c0c',
                foreground: '#cccccc',
                cursor: '#ffffff',
                black: '#0c0c0c',
                red: '#c50f1f',
                green: '#13a10e',
                yellow: '#c19c00',
                blue: '#0037da',
                magenta: '#881798',
                cyan: '#3a96dd',
                white: '#cccccc',
                brightBlack: '#767676',
                brightRed: '#e74856',
                brightGreen: '#16c60c',
                brightYellow: '#f9f1a5',
                brightBlue: '#3b78ff',
                brightMagenta: '#b4009e',
                brightCyan: '#61d6d6',
                brightWhite: '#f2f2f2'
            }}
        }});

        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        fitAddon.fit();

        // 响应窗口大小变化
        window.addEventListener('resize', () => {{
            fitAddon.fit();
        }});

        let ws = null;
        const statusEl = document.getElementById('status');

        // 自动连接到 WebSocket 服务器
        function connect() {{
            statusEl.textContent = '连接中...';
            statusEl.className = 'status connecting';

            // 动态构建 WebSocket URL
            // 如果通过 ngrok 访问，使用相对路径；否则使用本地端口
            let wsUrl;
            if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {{
                // 本地访问：直接连接到 WebSocket 端口
                wsUrl = 'ws://127.0.0.1:{ws_port}';
            }} else {{
                // 通过 ngrok 访问：使用 ngrok 的 WebSocket 支持
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                wsUrl = `${{protocol}}//${{window.location.host}}`;
            }}

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {{
                statusEl.textContent = '已连接';
                statusEl.className = 'status connected';
                // 发送初始化消息，使用默认 shell
                ws.send(JSON.stringify({{ type: 'init', shell: 'powershell' }}));
            }};

            ws.onmessage = (event) => {{
                if (event.data instanceof Blob) {{
                    event.data.arrayBuffer().then(buffer => {{
                        const bytes = new Uint8Array(buffer);
                        term.write(bytes);
                    }});
                }} else if (typeof event.data === 'string') {{
                    try {{
                        const msg = JSON.parse(event.data);
                        if (msg.error) {{
                            term.writeln(`\\x1b[31m错误: ${{msg.error}}\\x1b[0m`);
                        }}
                    }} catch {{
                        term.write(event.data);
                    }}
                }}
            }};

            ws.onerror = (error) => {{
                term.writeln(`\\x1b[31m连接错误，请刷新页面重试\\x1b[0m`);
                statusEl.textContent = '连接失败';
                statusEl.className = 'status disconnected';
            }};

            ws.onclose = () => {{
                statusEl.textContent = '已断开';
                statusEl.className = 'status disconnected';
                ws = null;
            }};
        }}

        // 监听终端输入并发送到 WebSocket
        term.onData(data => {{
            if (ws && ws.readyState === WebSocket.OPEN) {{
                ws.send(data);
            }}
        }});

        // 页面加载后自动连接
        window.addEventListener('load', () => {{
            setTimeout(connect, 500);
        }});
    </script>
</body>
</html>
"""
    else:
        # 简单模式
        html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Web CLI</title>
    <style>
        body {
            font-family: 'Courier New', monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        h1 {
            color: #4ec9b0;
            margin: 0 0 20px 0;
        }
        #terminal {
            flex: 1;
            background: #0c0c0c;
            border: 2px solid #4ec9b0;
            border-radius: 8px;
            padding: 15px;
            overflow-y: auto;
            font-size: 14px;
        }
        .prompt {
            color: #4ec9b0;
        }
        .output {
            color: #d4d4d4;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <h1>🖥️ Web CLI Terminal</h1>
    <div id="terminal">
        <div class="output">Welcome to Web CLI!</div>
        <div class="output">This is a simple web-based command line interface.</div>
        <div class="output">More features coming soon...</div>
        <br>
        <div class="prompt">$ <span class="output">Ready for commands</span></div>
    </div>
</body>
</html>
"""

    html_file.write_text(html_content, encoding="utf-8")

    # 使用 Python 内置的 http.server，明确绑定到 127.0.0.1
    process = subprocess.Popen(
        ["python", "-m", "http.server", str(port), "--directory", str(html_dir), "--bind", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    )

    logger.info(f"Web 服务器已启动在端口 {port}")
    return process


def _kill_existing_ngrok():
    """关闭所有正在运行的 ngrok 进程"""
    try:
        # 使用 PowerShell 查找并杀死 ngrok 进程
        ps_script = '''
        $ngrokProcesses = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
        if ($ngrokProcesses) {
            $killed = @()
            foreach ($proc in $ngrokProcesses) {
                try {
                    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                    $killed += "$($proc.Id):ngrok"
                } catch {}
            }
            Write-Output ($killed -join ',')
        } else {
            Write-Output "NO_PROCESS"
        }
        '''
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout.strip()
        if output != "NO_PROCESS":
            logger.info(f"已关闭现有的 ngrok 进程: {output}")
            # 给 ngrok 一些时间来完全释放端点
            import time
            time.sleep(2)
    except Exception as e:
        logger.warning(f"关闭现有 ngrok 进程时出错: {e}")


def _start_ngrok(port: int = 8080, ws_port: int = 8081) -> tuple[Optional[str], Optional[str]]:
    """启动 ngrok 并返回公网 URL（HTTP 和 WebSocket）"""
    global _ngrok_process, _ngrok_url

    with _ngrok_lock:
        # 先停止任何已存在的 ngrok 进程（解决 ERR_NGROK_334 错误）
        _kill_existing_ngrok()

        # 如果已有管理的进程，也停止它
        if _ngrok_process and _ngrok_process.poll() is None:
            try:
                _ngrok_process.terminate()
                _ngrok_process.wait(timeout=3)
            except:
                _ngrok_process.kill()
            _ngrok_process = None
            _ngrok_url = None

        try:
            # 确保 ngrok 配置目录存在且包含 authtoken
            _ensure_ngrok_config()

            # 构建 ngrok 可执行文件路径
            if NGROK_DIR and os.path.isdir(NGROK_DIR):
                ngrok_exe = os.path.join(NGROK_DIR, "ngrok.exe")
                if not os.path.isfile(ngrok_exe):
                    # 尝试不带 .exe 后缀
                    ngrok_exe = os.path.join(NGROK_DIR, "ngrok")
                logger.info(f"使用配置的 ngrok 路径: {ngrok_exe}")
            else:
                ngrok_exe = "ngrok"
                logger.info("使用系统 PATH 中的 ngrok")

            # 启动 ngrok（同时转发 WebSocket 端口）
            # 使用 ngrok 的 HTTP 隧道，它会自动支持 WebSocket 升级
            _ngrok_process = subprocess.Popen(
                [ngrok_exe, "http", f"http://127.0.0.1:{ws_port}", "--log=stdout"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            # 等待 ngrok 启动并获取 URL
            import time
            time.sleep(3)  # 给 ngrok 一些启动时间

            # 检查 ngrok 进程是否还在运行
            if _ngrok_process.poll() is not None:
                stderr = _ngrok_process.stderr.read() if _ngrok_process.stderr else ""
                logger.error(f"ngrok 进程异常退出: {stderr}")
                return None, None

            # 通过 ngrok API 获取 URL（最多重试 5 次）
            import json
            import urllib.request

            for attempt in range(5):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=5) as response:
                        data = json.loads(response.read())
                        tunnels = data.get("tunnels", [])
                        if tunnels:
                            _ngrok_url = tunnels[0].get("public_url", "")
                            # WebSocket URL 使用相同的 URL（ngrok 自动支持 WebSocket 升级）
                            ws_url = _ngrok_url.replace("http://", "ws://").replace("https://", "wss://")
                            logger.info(f"ngrok HTTP URL: {_ngrok_url}")
                            logger.info(f"ngrok WebSocket URL: {ws_url}")
                            return _ngrok_url, ws_url
                        else:
                            logger.warning(f"ngrok 没有活跃的隧道 (尝试 {attempt + 1}/5)")
                except Exception as e:
                    logger.warning(f"获取 ngrok URL 失败 (尝试 {attempt + 1}/5): {e}")
                time.sleep(2)

            # 获取 ngrok 日志以诊断问题
            try:
                # 尝试读取 ngrok 的输出
                import select
                if hasattr(select, 'select'):
                    readable, _, _ = select.select([_ngrok_process.stdout], [], [], 1)
                    if readable:
                        log_line = _ngrok_process.stdout.readline()
                        logger.error(f"ngrok 日志: {log_line.strip()}")
            except:
                pass

            return None, None

        except Exception as e:
            logger.error(f"启动 ngrok 失败: {e}")
            return None, None


def _ensure_ngrok_config():
    """确保 ngrok 配置文件存在且包含 authtoken"""
    try:
        # ngrok 配置文件路径（Windows）
        config_dir = Path.home() / ".ngrok2"
        config_file = config_dir / "ngrok.yml"
        
        # 也检查新的配置路径
        config_dir2 = Path.home() / ".config" / "ngrok"
        config_file2 = config_dir2 / "ngrok.yml"
        
        # 检查是否已有配置
        config_exists = False
        if config_file.exists():
            content = config_file.read_text()
            if "authtoken" in content:
                config_exists = True
        elif config_file2.exists():
            content = config_file2.read_text()
            if "authtoken" in content:
                config_exists = True
        
        # 如果没有配置，创建它
        if not config_exists and NGROK_AUTHTOKEN:
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file.write_text(f"authtoken: {NGROK_AUTHTOKEN}\n", encoding="utf-8")
            logger.info(f"已创建 ngrok 配置文件: {config_file}")
    except Exception as e:
        logger.warning(f"确保 ngrok 配置时出错: {e}")


def stop_webcli_services():
    """停止 web 服务器和 ngrok"""
    global _ngrok_process, _web_server_process, _ngrok_url

    with _ngrok_lock:
        if _ngrok_process:
            try:
                _ngrok_process.terminate()
                _ngrok_process.wait(timeout=3)
            except:
                _ngrok_process.kill()
            _ngrok_process = None
            _ngrok_url = None
            logger.info("ngrok 已停止")

        if _web_server_process:
            try:
                _web_server_process.terminate()
                _web_server_process.wait(timeout=3)
            except:
                _web_server_process.kill()
            _web_server_process = None
            logger.info("Web 服务器已停止")

    # 停止 TUI 服务器
    stop_tui_server()


async def handle_webcli_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 Web CLI 模式的启动"""
    global _web_server_process, _tui_mode

    user_id = update.effective_user.id
    
    # 发送正在处理的消息
    status_msg = await update.message.reply_text("🔄 正在启动 Web CLI...")

    # 步骤1: 关闭占用 8081 端口的进程（TUI 服务器端口）
    await status_msg.edit_text("🔄 步骤 1/2: 正在关闭占用 8081 端口的进程...")
    success, message = await asyncio.get_event_loop().run_in_executor(None, _kill_port_processes, 8081)
    if not success:
        await status_msg.edit_text(f"❌ {message}")
        return
    logger.info(message)

    # 步骤2: 启动 TUI 服务器（HTTP + WebSocket 在同一端口）
    await status_msg.edit_text("🔄 步骤 2/3: 正在启动 TUI 服务器...")
    _tui_mode = True

    # 启动 TUI 服务器（包含 HTTP 和 WebSocket）
    try:
        start_tui_server_background(port=8081, default_shell="powershell")
        logger.info("TUI 服务器已启动 (HTTP + WebSocket on port 8081)")
    except Exception as e:
        logger.error(f"启动 TUI 服务器失败: {e}")
        await status_msg.edit_text(f"❌ 启动 TUI 服务器失败: {e}")
        return

    # 步骤3: 启动 ngrok（转发 8081 端口）
    await status_msg.edit_text("🔄 步骤 3/3: 正在启动 ngrok 隧道...")
    http_url, ws_url = _start_ngrok(port=8080, ws_port=8081)

    if ws_url:
        await status_msg.edit_text(
            f"🌐 <b>Web CLI 已启动！</b>\n\n"
            f"📱 点击下方链接访问 PowerShell 终端:\n"
            f"<a href='{ws_url}'>{ws_url}</a>\n\n"
            f"💡 <b>使用说明:</b>\n"
            f"• 网页打开后自动连接到 PowerShell\n"
            f"• 你可以在终端中运行任何命令\n"
            f"• 支持启动 Kimi、Claude、Codex 等 CLI 工具\n"
            f"• 使用 /stop 命令停止服务",
            parse_mode="HTML"
        )
    else:
        await status_msg.edit_text(
            "❌ 启动失败\n\n"
            "请确保:\n"
            "1. ngrok 已正确安装\n"
            "2. ngrok authtoken 已配置\n"
            "3. 网络连接正常"
        )


async def handle_webcli_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """停止 Web CLI 服务"""
    stop_webcli_services()
    await update.message.reply_text("✅ Web CLI 服务已停止")


async def handle_webcli_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看 Web CLI 状态"""
    global _ngrok_url, _ngrok_process, _web_server_process, _tui_mode

    web_status = "🟢 运行中" if _web_server_process and _web_server_process.poll() is None else "🔴 已停止"
    ngrok_status = "🟢 运行中" if _ngrok_process and _ngrok_process.poll() is None else "🔴 已停止"
    mode_text = "TUI 模式" if _tui_mode else "简单模式"

    message = (
        f"📊 <b>Web CLI 状态</b>\n\n"
        f"模式: {mode_text}\n"
        f"Web 服务器: {web_status}\n"
        f"ngrok 隧道: {ngrok_status}\n"
    )

    if _ngrok_url:
        message += f"\n🌐 访问地址:\n<a href='{_ngrok_url}'>{_ngrok_url}</a>"

    await update.message.reply_html(message)
