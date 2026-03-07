"""Combined HTTP + WebSocket server for webcli"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol
from aiohttp import web

logger = logging.getLogger(__name__)


async def handle_websocket(websocket: WebSocketServerProtocol):
    """处理 WebSocket 连接 - 转发到 PowerShell"""
    logger.info(f"WebSocket 连接建立: {websocket.remote_address}")

    process: Optional[subprocess.Popen] = None

    try:
        # 等待客户端发送初始化消息
        init_message = await websocket.recv()
        logger.info(f"收到初始化消息: {init_message}")

        # 解析初始化消息
        try:
            init_data = json.loads(init_message)
        except json.JSONDecodeError:
            init_data = {}

        # 启动 PowerShell
        command = ["powershell.exe", "-NoLogo", "-NoExit"]
        cwd = init_data.get("cwd", os.getcwd())

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )

        logger.info(f"PowerShell 进程已启动: PID={process.pid}")

        # 创建双向转发任务
        async def forward_output():
            """从 PowerShell 读取输出并转发到 WebSocket"""
            try:
                while process.poll() is None:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, process.stdout.read, 1024
                    )
                    if data:
                        await websocket.send(data)
            except Exception as e:
                logger.error(f"转发输出时出错: {e}")

        async def forward_input():
            """从 WebSocket 接收输入并转发到 PowerShell"""
            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        process.stdin.write(message)
                        process.stdin.flush()
                    elif isinstance(message, str):
                        data = message.encode('utf-8')
                        process.stdin.write(data)
                        process.stdin.flush()
            except websockets.exceptions.ConnectionClosed:
                logger.info("WebSocket 连接已关闭")
            except Exception as e:
                logger.error(f"转发输入时出错: {e}")

        # 并发执行双向转发
        await asyncio.gather(
            forward_output(),
            forward_input(),
            return_exceptions=True
        )

    except Exception as e:
        logger.error(f"WebSocket 处理出错: {e}")
        try:
            await websocket.send(json.dumps({"error": str(e)}))
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
        logger.info("WebSocket 连接已关闭")


async def handle_http(request):
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


async def start_combined_server(port: int = 8081):
    """启动组合服务器（HTTP + WebSocket）"""
    # 创建 aiohttp 应用
    app = web.Application()
    app.router.add_get('/', handle_http)

    # 启动 HTTP 服务器
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', port)
    await site.start()

    logger.info(f"HTTP 服务器已启动在端口 {port}")

    # 启动 WebSocket 服务器（在同一端口的 /ws 路径）
    async with websockets.serve(handle_websocket, "127.0.0.1", port, path="/ws"):
        logger.info(f"WebSocket 服务器已启动在端口 {port}/ws")
        await asyncio.Future()  # 永久运行
