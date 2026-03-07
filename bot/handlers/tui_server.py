"""TUI WebSocket 服务器 - 支持原始字节流转发 + HTTP 服务"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from aiohttp import web
import aiohttp

logger = logging.getLogger(__name__)

# 全局变量存储服务器实例
_tui_server: Optional[asyncio.Task] = None
_tui_port: int = 8081
_default_shell: str = "powershell"  # 默认 shell 类型


async def handle_tui_websocket(request):
    """处理 TUI WebSocket 连接 - 转发原始字节流"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info(f"TUI WebSocket 连接建立: {request.remote}")

    process: Optional[subprocess.Popen] = None
    master_fd = None

    try:
        # 等待客户端发送初始化消息
        msg = await ws.receive()
        init_message = msg.data
        logger.info(f"收到初始化消息: {init_message}")

        # 解析初始化消息
        try:
            init_data = json.loads(init_message)
        except json.JSONDecodeError:
            init_data = {}

        # 确定要启动的 shell
        shell_type = init_data.get("shell", _default_shell)

        # 根据 shell 类型构建命令
        if shell_type == "powershell":
            # 启动 PowerShell，设置 UTF-8 编码以支持中文
            if sys.platform == "win32":
                command = [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoExit",
                    "-Command",
                    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; chcp 65001 | Out-Null"
                ]
            else:
                # Unix 系统尝试使用 pwsh 或 powershell
                command = ["pwsh", "-NoLogo", "-NoExit"]
        elif shell_type == "cmd":
            command = ["cmd.exe"]
        elif shell_type == "bash":
            command = ["bash"]
        else:
            # 使用自定义命令
            command = init_data.get("command", [])
            if not command:
                await ws.send_json({"error": "No command specified"})
                return ws

        cwd = init_data.get("cwd", os.getcwd())

        # 启动 CLI 进程（使用 PTY 模式以支持 ANSI 转义序列）
        # Windows 不支持 PTY，使用 subprocess.PIPE
        if sys.platform == "win32":
            # Windows: 使用 ConPTY (需要 Python 3.8+)
            # 设置环境变量确保 UTF-8 编码
            env = {
                **os.environ,
                "FORCE_COLOR": "1",
                "TERM": "xterm-256color",
                "PYTHONIOENCODING": "utf-8",
                "CHCP": "65001"
            }
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                bufsize=0  # 无缓冲模式，实时输出
            )
        else:
            # Unix: 使用 PTY
            import pty
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
                preexec_fn=os.setsid
            )
            os.close(slave_fd)

        logger.info(f"CLI 进程已启动: PID={process.pid}")

        # 创建双向转发任务
        async def forward_output():
            """从 CLI 进程读取输出并转发到 WebSocket"""
            try:
                if sys.platform == "win32":
                    # Windows: 从 stdout 读取 - 使用小缓冲区并立即发送
                    import msvcrt
                    # 设置 stdout 为非阻塞模式
                    import sys
                    
                    while process.poll() is None:
                        # 使用 read1 进行更高效的流式读取，小缓冲区确保低延迟
                        data = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: process.stdout.read1(256) if hasattr(process.stdout, 'read1') else process.stdout.read(256)
                        )
                        if data:
                            await ws.send_bytes(data)
                            # 立即刷新，确保实时性
                            await asyncio.sleep(0.001)
                        else:
                            # 无数据时短暂休眠，避免 CPU 占用过高
                            await asyncio.sleep(0.01)
                else:
                    # Unix: 从 PTY master 读取
                    while process.poll() is None:
                        data = await asyncio.get_event_loop().run_in_executor(
                            None, os.read, master_fd, 256
                        )
                        if data:
                            await ws.send_bytes(data)
                            await asyncio.sleep(0.001)
                        else:
                            await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"转发输出时出错: {e}")

        async def forward_input():
            """从 WebSocket 接收输入并转发到 CLI 进程"""
            try:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        # 原始字节流
                        if sys.platform == "win32":
                            process.stdin.write(msg.data)
                            process.stdin.flush()
                        else:
                            os.write(master_fd, msg.data)
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        # 文本消息（转换为字节）
                        data = msg.data.encode('utf-8')
                        if sys.platform == "win32":
                            process.stdin.write(data)
                            process.stdin.flush()
                        else:
                            os.write(master_fd, data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f'WebSocket 错误: {ws.exception()}')
                        break
            except Exception as e:
                logger.error(f"转发输入时出错: {e}")

        # 并发执行双向转发
        await asyncio.gather(
            forward_output(),
            forward_input(),
            return_exceptions=True
        )

    except Exception as e:
        logger.error(f"TUI WebSocket 处理出错: {e}")
        try:
            await ws.send_json({"error": str(e)})
        except:
            pass
    finally:
        # 清理进程
        if process:
            try:
                process.terminate()
                process.wait(timeout=3)
            except:
                process.kill()
        logger.info("TUI WebSocket 连接已关闭")

    return ws


async def handle_http_index(request):
    """处理 HTTP 请求 - 返回 HTML 页面"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PowerShell Web Terminal</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
    <style>
        body {
            margin: 0;
            padding: 0;
            background: #0c0c0c;
            display: flex;
            flex-direction: column;
            height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .header {
            background: #1e1e1e;
            color: #cccccc;
            padding: 10px 20px;
            border-bottom: 1px solid #333;
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
        }
        .header h1 {
            margin: 0;
            font-size: 14px;
            font-weight: 500;
        }
        .status {
            margin-left: auto;
            font-size: 12px;
            padding: 2px 8px;
            border-radius: 3px;
            background: #333;
        }
        .status.connecting { color: #f9f1a5; }
        .status.connected { color: #16c60c; background: #0d3b0d; }
        .status.disconnected { color: #e74856; }
        #terminal-container {
            flex: 1;
            overflow: hidden;
        }
        #terminal {
            width: 100%;
            height: 100%;
            padding: 5px;
        }
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
        const term = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: '"Cascadia Code", "Courier New", "Consolas", monospace',
            theme: {
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
            }
        });

        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        fitAddon.fit();

        // 响应窗口大小变化
        window.addEventListener('resize', () => {
            fitAddon.fit();
        });

        let ws = null;
        const statusEl = document.getElementById('status');

        // 自动连接到 WebSocket
        function connect() {
            statusEl.textContent = '连接中...';
            statusEl.className = 'status connecting';

            // 动态构建 WebSocket URL（支持 ngrok）
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws`;

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                statusEl.textContent = '已连接';
                statusEl.className = 'status connected';
                // 发送初始化消息
                ws.send(JSON.stringify({ type: 'init', shell: 'powershell' }));
            };

            ws.onmessage = (event) => {
                if (event.data instanceof Blob) {
                    event.data.arrayBuffer().then(buffer => {
                        const bytes = new Uint8Array(buffer);
                        term.write(bytes);
                    });
                } else if (typeof event.data === 'string') {
                    try {
                        const msg = JSON.parse(event.data);
                        if (msg.error) {
                            term.writeln(`\\x1b[31m错误: ${msg.error}\\x1b[0m`);
                        }
                    } catch {
                        term.write(event.data);
                    }
                }
            };

            ws.onerror = (error) => {
                term.writeln(`\\x1b[31m连接错误，请刷新页面重试\\x1b[0m`);
                statusEl.textContent = '连接失败';
                statusEl.className = 'status disconnected';
            };

            ws.onclose = () => {
                statusEl.textContent = '已断开';
                statusEl.className = 'status disconnected';
                ws = null;
            };
        }

        // 监听终端输入并发送到 WebSocket
        term.onData(data => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(data);
            }
        });

        // 页面加载后自动连接
        window.addEventListener('load', () => {
            setTimeout(connect, 500);
        });
    </script>
</body>
</html>
"""
    return web.Response(text=html_content, content_type='text/html')


async def start_tui_server(port: int = 8081):
    """启动 TUI 服务器（HTTP + WebSocket）"""
    global _tui_server, _tui_port

    _tui_port = port

    # 创建 aiohttp 应用
    app = web.Application()
    app.router.add_get('/', handle_http_index)
    app.router.add_get('/ws', handle_tui_websocket)

    # 启动服务器
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', port)
    await site.start()

    logger.info(f"TUI 服务器（HTTP + WebSocket）已启动在端口 {port}")
    await asyncio.Future()  # 永久运行


def start_tui_server_background(port: int = 8081, default_shell: str = "powershell") -> asyncio.Task:
    """在后台启动 TUI WebSocket 服务器"""
    global _tui_server, _default_shell

    _default_shell = default_shell

    if _tui_server and not _tui_server.done():
        logger.info("TUI 服务器已在运行")
        return _tui_server

    loop = asyncio.get_event_loop()
    _tui_server = loop.create_task(start_tui_server(port))
    return _tui_server


def stop_tui_server():
    """停止 TUI WebSocket 服务器"""
    global _tui_server

    if _tui_server and not _tui_server.done():
        _tui_server.cancel()
        _tui_server = None
        logger.info("TUI 服务器已停止")
