"""TUI WebSocket 服务器 - 支持原始字节流转发 + HTTP 服务"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Union

from aiohttp import web
import aiohttp

logger = logging.getLogger(__name__)

# 全局变量存储服务器实例
_tui_server: Optional[asyncio.Task] = None
_tui_port: int = 8081
_default_shell: str = "powershell"  # 默认 shell 类型

# 尝试导入 winpty（Windows PTY 支持）
try:
    from winpty import PtyProcess
    _WINPTY_AVAILABLE = True
    logger.info("winpty 已加载，PTY 模式可用")
except ImportError:
    _WINPTY_AVAILABLE = False
    logger.warning("winpty 未安装，PTY 模式不可用，交互式程序可能无法正常工作")


class PtyWrapper:
    """统一 winpty.PtyProcess 和 subprocess.Popen 的接口"""
    
    def __init__(self, process: Union[subprocess.Popen, 'PtyProcess'], is_pty: bool = False):
        self.process = process
        self.is_pty = is_pty
        self._lock = threading.Lock()
    
    def read(self, timeout: int = 1000) -> bytes:
        """读取输出"""
        if self.is_pty:
            try:
                # winpty.PtyProcess.read() 只接受 size 参数，不接受 timeout 关键字参数。
                # 之前这里一直抛 TypeError 并被吞掉，导致 Web 终端永远读不到输出。
                return self.process.read(4096)
            except Exception:
                return b""
        else:
            # 对于 subprocess，使用非阻塞读取
            if hasattr(self.process.stdout, 'read1'):
                data = self.process.stdout.read1(4096)
            else:
                data = self.process.stdout.read(4096)
            return data if data else b""
    
    def write(self, data: bytes) -> None:
        """写入输入"""
        with self._lock:
            if self.is_pty:
                self.process.write(data.decode('utf-8', errors='replace'))
            else:
                self.process.stdin.write(data)
                self.process.stdin.flush()
    
    def isalive(self) -> bool:
        """检查进程是否存活"""
        if self.is_pty:
            return self.process.isalive()
        else:
            return self.process.poll() is None
    
    def terminate(self) -> None:
        """终止进程"""
        if self.is_pty:
            try:
                self.process.terminate()
            except:
                pass
        else:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except:
                self.process.kill()
    
    def close(self) -> None:
        """关闭进程"""
        if self.is_pty:
            try:
                self.process.close()
            except:
                pass
    
    @property
    def pid(self) -> int:
        """获取进程 ID"""
        if self.is_pty:
            return self.process.pid
        else:
            return self.process.pid


def create_shell_process(shell_type: str, cwd: str, use_pty: bool = True) -> PtyWrapper:
    """创建 shell 进程，优先使用 PTY 模式"""
    
    # 构建命令
    if shell_type == "powershell":
        if sys.platform == "win32":
            # 使用 -NoExit 确保 PowerShell 保持运行
            cmdline = "powershell.exe -NoLogo -NoExit"
        else:
            cmdline = "pwsh -NoLogo -NoExit"
    elif shell_type == "cmd":
        cmdline = "cmd.exe"
    elif shell_type == "bash":
        cmdline = "bash"
    else:
        cmdline = shell_type
    
    # Windows: 尝试使用 winpty
    if sys.platform == "win32" and use_pty and _WINPTY_AVAILABLE:
        try:
            logger.info(f"使用 winpty 启动 shell: {cmdline}")
            env = {
                **os.environ,
                "FORCE_COLOR": "1",
                "TERM": "xterm-256color",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "KIMI_CLI_MODE": "1",  # 标记 Kimi CLI 模式
            }
            logger.debug(f"环境变量: {env.keys()}")
            process = PtyProcess.spawn(
                cmdline,
                cwd=cwd,
                dimensions=(40, 120),  # (rows, cols)
                env=env
            )
            logger.info(f"winpty 进程已创建: PID={process.pid}")
            return PtyWrapper(process, is_pty=True)
        except Exception as e:
            logger.warning(f"winpty 启动失败，回退到 subprocess: {e}")
            import traceback
            logger.warning(traceback.format_exc())
    
    # 回退到 subprocess.PIPE 模式
    logger.info(f"使用 subprocess 启动 shell: {cmdline}")
    
    if sys.platform == "win32":
        env = {
            **os.environ,
            "FORCE_COLOR": "1",
            "TERM": "xterm-256color",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "CHCP": "65001"
        }
        # 将命令拆分为列表
        cmd_parts = cmdline.split()
        process = subprocess.Popen(
            cmd_parts,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            bufsize=0
        )
    else:
        # Unix: 使用 PTY
        import pty
        master_fd, slave_fd = pty.openpty()
        cmd_parts = cmdline.split()
        process = subprocess.Popen(
            cmd_parts,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
            preexec_fn=os.setsid
        )
        os.close(slave_fd)
        # Unix PTY 暂时用原生方式处理
        return PtyWrapper(process, is_pty=False)
    
    return PtyWrapper(process, is_pty=False)


async def handle_tui_websocket(request):
    """处理 TUI WebSocket 连接 - 转发原始字节流"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info(f"TUI WebSocket 连接建立: {request.remote}")

    process: Optional[PtyWrapper] = None

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
        cwd = init_data.get("cwd", os.getcwd())
        
        # 检查是否强制禁用 PTY（用于调试）
        force_no_pty = init_data.get("no_pty", False)
        use_pty = not force_no_pty

        # 启动 shell 进程
        process = create_shell_process(shell_type, cwd, use_pty=use_pty)
        logger.info(f"CLI 进程已启动: PID={process.pid}, PTY={process.is_pty}")
        
        # 告知客户端 PTY 模式状态
        try:
            await ws.send_json({"pty_mode": process.is_pty})
        except:
            pass

        # 创建双向转发任务
        async def forward_output():
            """从 CLI 进程读取输出并转发到 WebSocket"""
            try:
                last_alive_check = time.time()
                while True:
                    # 在 executor 中读取以避免阻塞事件循环
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: process.read(timeout=100)
                    )
                    if data:
                        if isinstance(data, str):
                            data = data.encode('utf-8', errors='replace')
                        await ws.send_bytes(data)
                        logger.debug(f"转发 {len(data)} 字节到 WebSocket")
                        # 短暂休眠以避免 CPU 占用过高
                        await asyncio.sleep(0.001)
                    else:
                        await asyncio.sleep(0.1)  # 100ms 轮询
                    
                    # 定期检查进程状态（每秒一次）
                    now = time.time()
                    if now - last_alive_check >= 1.0:
                        last_alive_check = now
                        if not process.isalive():
                            logger.info(f"CLI 进程已退出 (PID={process.pid})")
                            break
            except Exception as e:
                logger.error(f"转发输出时出错: {e}")
                import traceback
                logger.error(traceback.format_exc())

        async def forward_input():
            """从 WebSocket 接收输入并转发到 CLI 进程"""
            try:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        # 原始字节流
                        process.write(msg.data)
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        # 文本消息（转换为字节）
                        process.write(msg.data.encode('utf-8'))
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
                process.close()
            except:
                pass
        logger.info("TUI WebSocket 连接已关闭")

    return ws


async def handle_http_index(request):
    """处理 HTTP 请求 - 返回 HTML 页面（支持移动端）"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>PowerShell Web Terminal</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
    <style>
        * {
            box-sizing: border-box;
        }
        html, body {
            margin: 0;
            padding: 0;
            background: #0c0c0c;
            height: 100%;
            width: 100%;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            touch-action: manipulation;
        }
        body {
            display: flex;
            flex-direction: column;
        }
        .header {
            background: #1e1e1e;
            color: #cccccc;
            padding: 10px 15px;
            border-bottom: 1px solid #333;
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
            flex-shrink: 0;
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
        .pty-indicator {
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 3px;
            background: #0d3b0d;
            color: #16c60c;
        }
        .pty-indicator.disabled {
            background: #3b0d0d;
            color: #e74856;
        }
        #terminal-container {
            flex: 1;
            overflow: hidden;
            position: relative;
        }
        #terminal {
            width: 100%;
            height: 100%;
            padding: 5px;
        }
        /* 移动端输入辅助层 */
        #mobile-input-layer {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0;
            cursor: text;
            z-index: 10;
        }
        #hidden-input {
            position: absolute;
            top: -1000px;
            left: -1000px;
            opacity: 0;
            font-size: 16px; /* 防止 iOS 缩放 */
        }
        /* 移动端工具栏 */
        .mobile-toolbar {
            display: none;
            background: #1e1e1e;
            border-top: 1px solid #333;
            padding: 5px;
            flex-shrink: 0;
            overflow-x: auto;
            white-space: nowrap;
            -webkit-overflow-scrolling: touch;
        }
        .mobile-toolbar button {
            background: #333;
            color: #ccc;
            border: none;
            padding: 8px 12px;
            margin: 2px;
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
            min-width: 44px;
            min-height: 36px;
        }
        .mobile-toolbar button:active {
            background: #555;
        }
        @media (pointer: coarse) {
            .mobile-toolbar {
                display: block;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🖥️ PowerShell Web Terminal</h1>
        <span id="pty-indicator" class="pty-indicator">PTY</span>
        <span class="status connecting" id="status">连接中...</span>
    </div>
    <div id="terminal-container">
        <div id="terminal"></div>
        <div id="mobile-input-layer"></div>
        <input type="text" id="hidden-input" autocomplete="off" autocorrect="off" 
               autocapitalize="off" spellcheck="false" />
    </div>
    <div class="mobile-toolbar" id="mobile-toolbar">
        <button onclick="sendKey('Ctrl+C')">Ctrl+C</button>
        <button onclick="sendKey('Ctrl+D')">Ctrl+D</button>
        <button onclick="sendKey('Ctrl+Z')">Ctrl+Z</button>
        <button onclick="sendKey('Tab')">Tab</button>
        <button onclick="sendKey('Escape')">Esc</button>
        <button onclick="sendKey('ArrowUp')">↑</button>
        <button onclick="sendKey('ArrowDown')">↓</button>
        <button onclick="sendKey('ArrowLeft')">←</button>
        <button onclick="sendKey('ArrowRight')">→</button>
        <button onclick="toggleKeyboard()">⌨️</button>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
    <script>
        // 检测是否为移动设备
        const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent) || 
                         (window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
        
        // 初始化 xterm.js
        const term = new Terminal({
            cursorBlink: true,
            fontSize: isMobile ? 12 : 14,
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
        const ptyIndicator = document.getElementById('pty-indicator');
        const hiddenInput = document.getElementById('hidden-input');
        const mobileInputLayer = document.getElementById('mobile-input-layer');

        // 发送特殊按键
        function sendKey(keyCombo) {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            
            const keyMap = {
                'Ctrl+C': '\\x03',
                'Ctrl+D': '\\x04',
                'Ctrl+Z': '\\x1A',
                'Tab': '\\t',
                'Escape': '\\x1B',
                'ArrowUp': '\\x1B[A',
                'ArrowDown': '\\x1B[B',
                'ArrowLeft': '\\x1B[D',
                'ArrowRight': '\\x1B[C'
            };
            
            const seq = keyMap[keyCombo];
            if (seq) {
                ws.send(seq);
            }
        }

        // 切换虚拟键盘
        function toggleKeyboard() {
            hiddenInput.focus();
        }

        // 移动端输入处理
        if (isMobile) {
            // 点击终端区域时聚焦隐藏输入框
            mobileInputLayer.addEventListener('touchstart', (e) => {
                e.preventDefault();
                hiddenInput.focus();
            });
            
            mobileInputLayer.addEventListener('click', (e) => {
                hiddenInput.focus();
            });

            // 处理隐藏输入框的输入事件
            let compositionBuffer = '';
            let isComposing = false;

            hiddenInput.addEventListener('compositionstart', () => {
                isComposing = true;
                compositionBuffer = '';
            });

            hiddenInput.addEventListener('compositionupdate', (e) => {
                compositionBuffer = e.data;
            });

            hiddenInput.addEventListener('compositionend', (e) => {
                isComposing = false;
                if (ws && ws.readyState === WebSocket.OPEN && e.data) {
                    ws.send(e.data);
                }
                compositionBuffer = '';
                // 清空输入框以便下次输入
                hiddenInput.value = '';
            });

            hiddenInput.addEventListener('input', (e) => {
                if (isComposing) return;
                
                if (ws && ws.readyState === WebSocket.OPEN) {
                    const value = e.target.value;
                    if (value) {
                        // 发送输入的字符
                        for (let i = 0; i < value.length; i++) {
                            ws.send(value[i]);
                        }
                    }
                }
                // 清空输入框
                e.target.value = '';
            });

            // 处理特殊按键
            hiddenInput.addEventListener('keydown', (e) => {
                if (isComposing) return;
                
                const keyMap = {
                    'Enter': '\\r',
                    'Backspace': '\\x7F',
                    'Delete': '\\x1B[3~',
                    'ArrowUp': '\\x1B[A',
                    'ArrowDown': '\\x1B[B',
                    'ArrowLeft': '\\x1B[D',
                    'ArrowRight': '\\x1B[C',
                    'Escape': '\\x1B',
                    'Tab': '\\t'
                };

                if (e.ctrlKey && e.key === 'c') {
                    e.preventDefault();
                    if (ws) ws.send('\\x03');
                } else if (e.ctrlKey && e.key === 'd') {
                    e.preventDefault();
                    if (ws) ws.send('\\x04');
                } else if (e.ctrlKey && e.key === 'z') {
                    e.preventDefault();
                    if (ws) ws.send('\\x1A');
                } else if (keyMap[e.key]) {
                    e.preventDefault();
                    if (ws) ws.send(keyMap[e.key]);
                }
            });
        }

        // 桌面端直接让终端获得焦点
        if (!isMobile) {
            term.focus();
        }

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
                
                // 移动端自动聚焦隐藏输入框
                if (isMobile) {
                    setTimeout(() => hiddenInput.focus(), 100);
                }
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
                        if (msg.pty_mode !== undefined) {
                            if (msg.pty_mode) {
                                ptyIndicator.textContent = 'PTY';
                                ptyIndicator.classList.remove('disabled');
                            } else {
                                ptyIndicator.textContent = 'PIPE';
                                ptyIndicator.classList.add('disabled');
                            }
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
    logger.info(f"PTY 模式: {'可用' if _WINPTY_AVAILABLE else '不可用'}")
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
