"""程序入口：启动/重启循环"""

import asyncio
import ctypes
import logging
import os
import socket
import sys
import time

# Windows 电源管理常量
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_CONTINUOUS = 0x80000000

# 确保 refactoring/ 在 sys.path 中，以便 `python bot/main.py` 也能正确导入 bot 包
_this_dir = os.path.dirname(os.path.abspath(__file__))          # refactoring/bot/
_package_root = os.path.dirname(_this_dir)                       # refactoring/
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

import bot.config as config
from bot.cli import validate_cli_type
from bot.config import (
    CLI_TYPE,
    CLI_PATH,
    MAIN_LOOP_RETRY_DELAY,
    MANAGED_BOTS_FILE,
    RESTART_EXIT_CODE,
    SESSION_TIMEOUT,
    WORKING_DIR,
    is_supervised_restart,
    reexec_current_process,
)
from bot.manager import MultiBotManager
from bot.messages import get_messages
from bot.models import BotProfile
from bot.version import APP_VERSION
from bot.web import WebApiServer

logger = logging.getLogger(__name__)


def safe_print(text: str = ""):
    """向控制台安全输出，避免 Windows 非 UTF-8 终端因 emoji 崩溃。"""
    try:
        print(text)
    except UnicodeEncodeError:
        stream = sys.stdout
        encoding = getattr(stream, "encoding", None) or "utf-8"
        sanitized = text.encode(encoding, errors="replace").decode(encoding, errors="ignore")
        stream.write(f"{sanitized}\n")


def _detect_lan_ipv4():
    """探测当前主机最适合展示给局域网访问的 IPv4 地址。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # UDP connect 不会真正发包，但能让系统选择默认出口网卡。
            probe.connect(("192.0.2.1", 80))
            candidate = probe.getsockname()[0]
            if candidate and not candidate.startswith("127."):
                return candidate
    except OSError:
        pass

    try:
        for family, socktype, proto, canonname, sockaddr in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        ):
            candidate = sockaddr[0]
            if candidate and not candidate.startswith("127."):
                return candidate
    except OSError:
        pass
    return None


def _format_http_host(host: str) -> str:
    normalized = (host or "").strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        return normalized
    if ":" in normalized:
        return f"[{normalized}]"
    return normalized


def _get_web_access_lines():
    """生成启动成功后展示给用户的 Web 访问地址。"""
    host = str(getattr(config, "WEB_HOST", "") or "").strip() or "127.0.0.1"
    port = int(getattr(config, "WEB_PORT", 8765))

    if host in {"0.0.0.0"}:
        lines = [f"   本机: http://127.0.0.1:{port}"]
        lan_ip = _detect_lan_ipv4()
        if lan_ip:
            lines.append(f"   局域网 IP: http://{lan_ip}:{port}")
        return lines
    if host in {"::", "[::]"}:
        return [f"   本机: http://[::1]:{port}"]

    if host in {"::1", "[::1]"}:
        return [f"   http://[::1]:{port}"]

    return [f"   http://{_format_http_host(host)}:{port}"]


def _print_web_access_lines():
    lines = _get_web_access_lines()
    if not lines:
        return
    safe_print("可访问地址:")
    for line in lines:
        safe_print(line)


def disable_console_quick_edit():
    """禁用 Windows 控制台快速编辑模式，避免点击控制台导致程序暂停"""
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            # 获取标准输入句柄
            stdin_handle = kernel32.GetStdHandle(-10)
            # 获取当前控制台模式
            mode = ctypes.c_uint32()
            kernel32.GetConsoleMode(stdin_handle, ctypes.byref(mode))
            # 禁用快速编辑模式 (ENABLE_QUICK_EDIT_MODE = 0x0040)
            # 禁用插入模式 (ENABLE_INSERT_MODE = 0x0020)
            new_mode = mode.value & ~0x0040 & ~0x0020
            kernel32.SetConsoleMode(stdin_handle, new_mode)
            logger.info("已禁用控制台快速编辑模式")
        except Exception as e:
            logger.warning(f"禁用快速编辑模式失败: {e}")


def prevent_system_sleep():
    """阻止系统进入睡眠状态"""
    if sys.platform == "win32":
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: 持续阻止系统睡眠
        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if result:
            logger.info("已阻止系统进入睡眠状态")
        else:
            logger.warning("阻止系统睡眠失败")


def restore_system_sleep():
    """恢复系统睡眠功能"""
    if sys.platform == "win32":
        # ES_CONTINUOUS: 清除之前的设置，恢复默认行为
        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        if result:
            logger.info("已恢复系统睡眠功能")
        else:
            logger.warning("恢复系统睡眠失败")


async def run_all_bots():
    config.RESTART_REQUESTED = False
    config.RESTART_EVENT = asyncio.Event()
    if not config.WEB_ENABLED:
        raise RuntimeError("WEB_ENABLED 不能为 false")

    main_profile = BotProfile(
        alias="main",
        cli_type=CLI_TYPE,
        cli_path=CLI_PATH,
        working_dir=WORKING_DIR,
        enabled=True,
    )

    manager = MultiBotManager(main_profile=main_profile, storage_file=MANAGED_BOTS_FILE)
    web_server = WebApiServer(manager)
    await web_server.start()
    logger.info("Web API 已附加到主进程")
    _print_web_access_lines()

    try:
        await config.RESTART_EVENT.wait()
    finally:
        await web_server.stop(preserve_tunnel=config.RESTART_REQUESTED)
        await manager.shutdown_all()
        # 保存所有会话到持久化存储
        from bot.sessions import save_all_sessions
        save_all_sessions()
        config.RESTART_EVENT = None
        # 注意：主bot关闭时不恢复睡眠，保持系统阻止睡眠状态
        # 如需恢复睡眠，请手动重启系统或执行 powercfg 命令
        # if not config.RESTART_REQUESTED:
        #     restore_system_sleep()


def main():
    msgs = get_messages()

    try:
        validate_cli_type(CLI_TYPE)
    except ValueError as e:
        safe_print(f"错误: {e}")
        sys.exit(1)

    safe_print(msgs.get("startup", "banner"))
    safe_print(msgs.get("startup", "title"))
    safe_print(f"  版本: {APP_VERSION}")
    safe_print(msgs.get("startup", "banner"))
    safe_print()
    safe_print(msgs.get("startup", "loading_config"))
    safe_print(f"   CLI类型: {CLI_TYPE}")
    safe_print(f"   工作目录: {WORKING_DIR}")
    safe_print(f"   会话超时: {SESSION_TIMEOUT}秒")
    safe_print(f"   托管配置: {MANAGED_BOTS_FILE}")
    safe_print(f"   Web API: {'开启' if config.WEB_ENABLED else '关闭'}")
    safe_print(msgs.get("startup", "loaded"))

    # 禁用控制台快速编辑模式，避免点击控制台导致程序暂停
    disable_console_quick_edit()

    # 阻止系统进入睡眠状态
    prevent_system_sleep()

    while True:
        config.RESTART_REQUESTED = False
        try:
            asyncio.run(run_all_bots())
        except KeyboardInterrupt:
            safe_print(f"\n{msgs.get('startup', 'shutdown')}")
            # 保存所有会话到持久化存储
            from bot.sessions import save_all_sessions
            save_all_sessions()
            break
        except Exception as e:
            logger.exception("运行异常，%s秒后自动重试: %s", MAIN_LOOP_RETRY_DELAY, e)
            safe_print(f"运行异常，将在 {MAIN_LOOP_RETRY_DELAY} 秒后自动重试: {e}")
            time.sleep(MAIN_LOOP_RETRY_DELAY)
            continue

        if config.RESTART_REQUESTED:
            safe_print(msgs.get("startup", "restart"))
            # 注意：重启前不恢复睡眠，避免屏幕盖着时系统进入睡眠
            # 新进程启动时会立即调用 prevent_system_sleep()
            # 短暂等待让启动问候消息的发送任务完成
            time.sleep(0.5)
            if is_supervised_restart():
                raise SystemExit(RESTART_EXIT_CODE)
            try:
                reexec_current_process()
            except Exception as e:
                safe_print(f"进程级重启失败: {e}")
                break
            break
        # 正常退出前保存会话
        from bot.sessions import save_all_sessions
        save_all_sessions()
        break

    # 注意：程序退出时不恢复系统睡眠，保持系统阻止睡眠状态
    # 如需恢复睡眠，请手动重启系统或执行 powercfg 命令
    # restore_system_sleep()


if __name__ == "__main__":
    main()
