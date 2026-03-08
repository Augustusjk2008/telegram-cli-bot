"""Kimi Web 模式处理器 - 启动 Kimi Web UI 并通过 Cloudflare Tunnel 公网转发"""

import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import NGROK_DIR

# 使用 NGROK_DIR 作为隧道工具目录（兼容旧配置）
TUNNEL_DIR = NGROK_DIR

logger = logging.getLogger(__name__)

# 全局变量存储进程和 URL
_kimi_process: Optional[subprocess.Popen] = None
_tunnel_process: Optional[subprocess.Popen] = None
_kimi_url: Optional[str] = None
_tunnel_url: Optional[str] = None
_kimi_token: Optional[str] = None
_process_lock = threading.Lock()

# Kimi Web 默认端口
KIMI_WEB_DEFAULT_PORT = 5494


def _is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """检查指定端口是否可连接"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _parse_kimi_output(line: str) -> dict:
    """解析 Kimi 输出，提取 token

    返回: {"token": str} 或空字典
    """
    # 匹配 Token 行: "Token:   cZPGXY53EFtRo8j5RkqdpHy-1S9KjLJgX7eFrwORMzM"
    token_match = re.search(r'Token:\s*([A-Za-z0-9_-]+)', line)
    if token_match:
        return {"token": token_match.group(1)}

    # 匹配 Local URL 中的 token: "➜  Local    http://localhost:5495/?token=xxx"
    url_match = re.search(r'\?token=([A-Za-z0-9_-]+)', line)
    if url_match:
        return {"token": url_match.group(1)}

    return {}


def _read_output_file(output_file: str, result_dict: dict):
    """后台线程：持续读取输出文件，解析 token"""
    try:
        with open(output_file, 'r', encoding='utf-8', errors='replace') as f:
            while True:
                line = f.readline()
                if line:
                    # 打印每一行输出，方便调试
                    logger.info(f"[Kimi Web 输出] {line.rstrip()}")
                    parsed = _parse_kimi_output(line)
                    if parsed and "token" in parsed:
                        result_dict.update(parsed)
                        logger.info(f"✓ 解析到 token: {parsed['token'][:10]}...")
                else:
                    import time
                    time.sleep(0.1)
    except Exception as e:
        logger.warning(f"读取 Kimi 输出时出错: {e}")


async def _start_kimi_web(cwd: str) -> tuple[Optional[subprocess.Popen], Optional[str]]:
    """启动 Kimi Web 模式，返回 (进程, 本地URL)"""
    try:
        # 先关闭已存在的 Kimi Web 进程，避免端口占用
        _kill_existing_kimi_web()

        # 等待端口释放
        for _ in range(20):
            if not _is_port_open(KIMI_WEB_DEFAULT_PORT):
                break
            await asyncio.sleep(0.1)

        # 设置环境变量
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # 启动 kimi web，不捕获输出，让它直接显示在控制台
        process = subprocess.Popen(
            ["kimi", "web", "--no-open", "--network", "--public"],
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )

        logger.info(f"Kimi Web 进程已启动: PID={process.pid}")

        # 等待端口开放
        for attempt in range(100):
            if process.poll() is not None:
                logger.error(f"Kimi Web 进程异常退出")
                return None, None

            if _is_port_open(KIMI_WEB_DEFAULT_PORT, timeout=0.5):
                local_url = f"http://127.0.0.1:{KIMI_WEB_DEFAULT_PORT}"
                logger.info(f"Kimi Web 已启动: {local_url}")
                return process, local_url

            await asyncio.sleep(0.1)

        logger.error("Kimi Web 端口未开放")
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            process.kill()
        return None, None

    except Exception as e:
        logger.error(f"启动 Kimi Web 失败: {e}")
        return None, None


def _kill_existing_processes(process_names: list[str]) -> list[str]:
    """关闭指定名称的进程
    
    Args:
        process_names: 要关闭的进程名称列表
        
    Returns:
        被关闭的进程信息列表
    """
    killed = []
    for name in process_names:
        try:
            ps_script = f'''
            $processes = Get-Process -Name "{name}" -ErrorAction SilentlyContinue
            if ($processes) {{
                $result = @()
                foreach ($proc in $processes) {{
                    try {{
                        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                        $result += "$($proc.Id)"
                    }} catch {{}}
                }}
                Write-Output ($result -join ',')
            }} else {{
                Write-Output "NO_PROCESS"
            }}
            '''
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout.strip()
            if output != "NO_PROCESS":
                killed.append(f"{name}:[{output}]")
        except Exception as e:
            logger.warning(f"关闭 {name} 进程时出错: {e}")
    return killed


def _kill_existing_tunnel():
    """关闭所有正在运行的 cloudflared 进程"""
    killed = _kill_existing_processes(["cloudflared"])
    if killed:
        logger.info(f"已关闭现有的 cloudflared 进程: {', '.join(killed)}")
        import time
        time.sleep(2)


def _kill_existing_kimi_web():
    """关闭所有正在运行的 Kimi Web 进程"""
    # Kimi Web 进程通常是 'kimi' 进程，参数中包含 'web'
    killed = _kill_existing_processes(["kimi"])
    if killed:
        logger.info(f"已关闭现有的 Kimi 进程: {', '.join(killed)}")
        import time
        time.sleep(1)


def _parse_cloudflared_output(line: str) -> Optional[str]:
    """解析 cloudflared 输出，提取公网 URL"""
    # 匹配类似: "https://xxx.trycloudflare.com"
    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
    if match:
        return match.group(0)
    return None


async def _start_cloudflared(local_url: str) -> Optional[str]:
    """启动 Cloudflare Tunnel 并返回公网 URL"""
    global _tunnel_process, _tunnel_url

    with _process_lock:
        _kill_existing_tunnel()

        if _tunnel_process and _tunnel_process.poll() is None:
            try:
                _tunnel_process.terminate()
                _tunnel_process.wait(timeout=3)
            except:
                _tunnel_process.kill()
            _tunnel_process = None
            _tunnel_url = None

        try:
            # 查找 cloudflared 可执行文件
            if TUNNEL_DIR and os.path.isdir(TUNNEL_DIR):
                cloudflared_exe = os.path.join(TUNNEL_DIR, "cloudflared.exe")
                if not os.path.isfile(cloudflared_exe):
                    cloudflared_exe = os.path.join(TUNNEL_DIR, "cloudflared")
                logger.info(f"使用配置的 cloudflared 路径: {cloudflared_exe}")
            else:
                cloudflared_exe = "cloudflared"
                logger.info("使用系统 PATH 中的 cloudflared")

            # 启动 cloudflared tunnel，使用临时隧道（无需登录）
            process = subprocess.Popen(
                [cloudflared_exe, "tunnel", "--url", local_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            _tunnel_process = process
            logger.info(f"cloudflared 进程已启动: PID={process.pid}")

            # 读取输出获取公网 URL
            tunnel_url = None
            for _ in range(100):  # 10秒超时
                if process.poll() is not None:
                    logger.error("cloudflared 进程异常退出")
                    return None

                try:
                    line = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, process.stdout.readline),
                        timeout=0.1
                    )
                    if line:
                        logger.info(f"[cloudflared] {line.rstrip()}")
                        url = _parse_cloudflared_output(line)
                        if url:
                            tunnel_url = url
                            _tunnel_url = url
                            logger.info(f"✓ Cloudflare Tunnel URL: {tunnel_url}")
                            # 启动后台线程继续读取输出，避免管道阻塞
                            threading.Thread(
                                target=lambda: [process.stdout.readline() for _ in iter(process.stdout.readline, '')],
                                daemon=True
                            ).start()
                            return tunnel_url
                except asyncio.TimeoutError:
                    pass

            logger.error("无法从 cloudflared 输出获取隧道 URL")
            try:
                process.terminate()
                process.wait(timeout=2)
            except:
                process.kill()
            return None

        except FileNotFoundError:
            logger.error(f"cloudflared 未找到。请将 cloudflared.exe 放到 {TUNNEL_DIR} 目录，或下载: https://github.com/cloudflare/cloudflared/releases")
            return None
        except Exception as e:
            logger.error(f"启动 cloudflared 失败: {e}")
            return None


def stop_kimi_web_services():
    """停止 Kimi Web 和 Cloudflare Tunnel 服务"""
    global _kimi_process, _tunnel_process, _kimi_url, _tunnel_url, _kimi_token

    with _process_lock:
        if _tunnel_process:
            try:
                _tunnel_process.terminate()
                _tunnel_process.wait(timeout=3)
            except:
                _tunnel_process.kill()
            _tunnel_process = None
            _tunnel_url = None
            logger.info("Cloudflare Tunnel 已停止")

        if _kimi_process:
            try:
                _kimi_process.terminate()
                _kimi_process.wait(timeout=3)
            except:
                _kimi_process.kill()
            _kimi_process = None
            _kimi_url = None
            _kimi_token = None
            logger.info("Kimi Web 已停止")


async def handle_kimi_web_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 Kimi Web 模式的启动 - 先启动 Cloudflare Tunnel"""
    global _tunnel_url, _kimi_url, _kimi_token

    status_msg = await update.message.reply_text("🔄 正在启动 Cloudflare Tunnel...")

    # 先启动 Cloudflare Tunnel，使用默认端口
    default_port = 5494
    temp_local_url = f"http://127.0.0.1:{default_port}"
    _tunnel_url = await _start_cloudflared(temp_local_url)

    if not _tunnel_url:
        await status_msg.edit_text(
            "❌ Cloudflare Tunnel 创建失败\n\n"
            "请确保:\n"
            "1. cloudflared 已正确安装\n"
            "2. 网络连接正常"
        )
        return

    # 返回 Tunnel URL，让用户用这个 URL 启动 Kimi Web
    await status_msg.edit_text(
        f"✅ Cloudflare Tunnel 已启动！\n\n"
        f"🌐 Tunnel URL: <code>{_tunnel_url}</code>\n\n"
        f"现在请在本地终端运行:\n"
        f"<code>kimi web --network --public --no-open --allowed-origins \"{_tunnel_url}\"</code>\n\n"
        f"启动后，从终端复制 <b>端口号</b> 并发送给我\n"
        f"（如果端口不是 5494，需要告诉我实际端口）",
        parse_mode="HTML"
    )

    # 设置用户状态，等待端口号输入
    from bot.context_helpers import get_current_session
    session = get_current_session(update, context)
    session.temp_data = {"waiting_for": "port", "tunnel_url": _tunnel_url}


async def handle_webcli_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 webcli 模式下的文本输入（端口号和 token）"""
    global _tunnel_url, _kimi_url, _kimi_token, _tunnel_process

    from bot.context_helpers import get_current_session
    session = get_current_session(update, context)

    if not hasattr(session, 'temp_data') or not session.temp_data:
        await update.message.reply_text("请先使用 /start 命令开始配置")
        return

    waiting_for = session.temp_data.get("waiting_for")

    if waiting_for == "port":
        # 接收端口号
        try:
            port = int(update.message.text.strip())
            if port < 1 or port > 65535:
                await update.message.reply_text("❌ 端口号无效，请输入 1-65535 之间的数字")
                return

            # 如果端口不是默认的 5494，需要重启 Cloudflare Tunnel
            if port != 5494:
                await update.message.reply_text(f"🔄 检测到端口 {port}，正在重启 Cloudflare Tunnel...")

                # 停止旧的 tunnel
                if _tunnel_process:
                    try:
                        _tunnel_process.terminate()
                        _tunnel_process.wait(timeout=3)
                    except:
                        _tunnel_process.kill()

                # 启动新的 tunnel
                new_local_url = f"http://127.0.0.1:{port}"
                _tunnel_url = await _start_cloudflared(new_local_url)

                if not _tunnel_url:
                    await update.message.reply_text("❌ 重启 Cloudflare Tunnel 失败")
                    session.temp_data = {}
                    return

                await update.message.reply_text(
                    f"✅ Cloudflare Tunnel 已更新到端口 {port}\n\n"
                    f"新的 Tunnel URL: <code>{_tunnel_url}</code>\n\n"
                    f"请重新启动 Kimi Web:\n"
                    f"<code>kimi web --network --public --no-open --allowed-origins \"{_tunnel_url}\" --port {port}</code>",
                    parse_mode="HTML"
                )

            session.temp_data["port"] = port
            session.temp_data["waiting_for"] = "token"
            _kimi_url = f"http://127.0.0.1:{port}"

            await update.message.reply_text(
                f"✅ 端口号: {port}\n\n"
                f"现在请从终端复制 Token 并发送给我\n\n"
                f"Token 格式示例:\n"
                f"<code>cZPGXY53EFtRo8j5RkqdpHy-1S9KjLJgX7eFrwORMzM</code>",
                parse_mode="HTML"
            )
        except ValueError:
            await update.message.reply_text("❌ 请输入有效的端口号（数字）")

    elif waiting_for == "token":
        # 接收 token
        token = update.message.text.strip()

        # 如果用户复制了完整的 URL，提取 token
        if "token=" in token:
            match = re.search(r'token=([A-Za-z0-9_-]+)', token)
            if match:
                token = match.group(1)

        if len(token) < 10:
            await update.message.reply_text("❌ Token 格式不正确，请重新输入")
            return

        _kimi_token = token

        # 清除临时数据
        session.temp_data = {}

        tunnel_url_with_token = f"{_tunnel_url}/?token={_kimi_token}"
        await update.message.reply_text(
            f"🌐 <b>Kimi Web 公网访问已就绪！</b>\n\n"
            f"📱 点击下方链接访问:\n"
            f"<a href='{tunnel_url_with_token}'>{tunnel_url_with_token}</a>\n\n"
            f"💡 使用 /stop 停止隧道\n"
            f"💡 使用 /status 查看状态\n\n"
            f"✅ 完全支持 WebSocket",
            parse_mode="HTML",
            disable_web_page_preview=True
        )


async def handle_kimi_web_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """停止 Cloudflare Tunnel 服务"""
    global _tunnel_process, _tunnel_url, _kimi_url, _kimi_token

    with _process_lock:
        if _tunnel_process:
            try:
                _tunnel_process.terminate()
                _tunnel_process.wait(timeout=3)
            except:
                _tunnel_process.kill()
            _tunnel_process = None
            _tunnel_url = None
            _kimi_url = None
            _kimi_token = None
            logger.info("Cloudflare Tunnel 已停止")

    await update.message.reply_text("✅ Cloudflare Tunnel 已停止")


async def handle_kimi_web_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看 Cloudflare Tunnel 状态"""
    global _tunnel_process, _kimi_url, _tunnel_url, _kimi_token

    tunnel_status = "🟢 运行中" if _tunnel_process and _tunnel_process.poll() is None else "🔴 已停止"

    message = f"📊 <b>Kimi Web 公网转发状态</b>\n\nCloudflare Tunnel: {tunnel_status}\n"

    if _kimi_url:
        message += f"\n🏠 本地地址:\n{_kimi_url}"

    if _tunnel_url and _kimi_token:
        tunnel_url_with_token = f"{_tunnel_url}/?token={_kimi_token}"
        message += f"\n\n🌐 公网地址:\n<a href='{tunnel_url_with_token}'>{tunnel_url_with_token}</a>"

    await update.message.reply_html(message, disable_web_page_preview=True)
