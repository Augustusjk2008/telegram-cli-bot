"""AI CLI 对话处理：进程管理、输出收集、会话续接"""

import asyncio
import html
import logging
import os
import queue
import select
import subprocess
import sys
import threading
import time
import uuid
from typing import List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CallbackQueryHandler

try:
    from httpx import ConnectError, ConnectTimeout, RemoteProtocolError
    HTTPX_ERRORS = (ConnectError, ConnectTimeout, RemoteProtocolError)
except ImportError:
    HTTPX_ERRORS = ()

from bot.cli import (
    build_cli_command,
    normalize_cli_type,
    parse_codex_json_output,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
    should_reset_kimi_session,
)
from bot.config import CLI_EXEC_TIMEOUT, CLI_PROGRESS_UPDATE_INTERVAL, CLI_TIMEOUT_CHECK_INTERVAL
from bot.context_helpers import get_current_profile, get_current_session
from bot.messages import msg
from bot.platform.processes import terminate_process_tree_sync
from bot.utils import check_auth, safe_edit_text, split_text_into_chunks

logger = logging.getLogger(__name__)


def get_stop_keyboard() -> InlineKeyboardMarkup:
    """获取带停止按钮的键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 停止任务", callback_data="stop_task")]
    ])


def _is_stop_requested(session) -> bool:
    if session is None:
        return False

    lock = getattr(session, "_lock", None)
    if lock is None:
        return bool(getattr(session, "stop_requested", False))

    with lock:
        return bool(getattr(session, "stop_requested", False))


def _terminate_process_tree_sync(process: subprocess.Popen):
    """同步终止进程及其子进程（Windows兼容），在 executor 线程中运行"""
    try:
        terminate_process_tree_sync(process)
    except Exception as e:
        logger.warning(f"终止进程时出错: {e}")


async def _terminate_process_tree(process: subprocess.Popen):
    """异步终止进程树；阻塞操作在 executor 线程中执行，不阻塞事件循环"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _terminate_process_tree_sync, process)


def _wait_for_process_exit_sync(process: subprocess.Popen, timeout: float) -> Optional[int]:
    try:
        return process.wait(timeout=timeout)
    except Exception:
        return None


async def _resolve_process_returncode(process: subprocess.Popen, current_returncode: Optional[int], wait_timeout: float = 1.0) -> int:
    if current_returncode is not None:
        return current_returncode

    polled = process.poll()
    if polled is not None:
        return polled

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _wait_for_process_exit_sync, process, wait_timeout)

    polled = process.poll()
    if polled is not None:
        return polled

    return -1


async def collect_cli_output(
    process: subprocess.Popen, update: Update, session=None
) -> Tuple[str, int, bool]:
    """运行CLI进程，显示等待提示，最后一次性返回所有输出。
    
    使用后台线程读取输出，主循环定期检查状态，支持响应停止信号。
    
    Returns:
        Tuple[str, int, bool]: (输出文本, 返回码, 是否因超时而终止)
    """
    loop = asyncio.get_running_loop()
    message = await update.message.reply_text(
        msg("chat", "processing"),
        reply_markup=get_stop_keyboard()
    )
    start_time = loop.time()
    timed_out = False

    # 用于收集输出的队列和列表
    output_queue: queue.Queue[str] = queue.Queue()
    output_lines: List[str] = []
    returncode_container: List[Optional[int]] = [None]
    stop_reading = threading.Event()

    def read_stdout():
        """后台线程：持续读取stdout到队列"""
        try:
            if process.stdout is None:
                return

            stdout = process.stdout
            fileno = stdout.fileno()

            # Windows 不支持 select，使用超时读取
            if sys.platform == "win32":
                for line in iter(stdout.readline, ''):
                    if stop_reading.is_set():
                        break
                    if line:
                        output_queue.put(line)
            else:
                # Unix: 使用 select 实现超时
                while not stop_reading.is_set():
                    readable, _, _ = select.select([fileno], [], [], 1.0)
                    if fileno in readable:
                        line = stdout.readline()
                        if not line:
                            break
                        output_queue.put(line)
                    # 检查进程是否已结束
                    if process.poll() is not None:
                        # 读取剩余输出
                        remaining = stdout.read()
                        if remaining:
                            for line in remaining.split('\n'):
                                if line:
                                    output_queue.put(line + '\n')
                        break
            
            # 获取返回码
            returncode_container[0] = process.poll()
        except Exception as e:
            logger.warning(f"读取stdout时出错: {e}")

    # 启动后台读取线程
    reader_thread = threading.Thread(target=read_stdout, daemon=True)
    reader_thread.start()

    # 状态跟踪
    last_update_time = 0

    try:
        while reader_thread.is_alive() or not output_queue.empty():
            await asyncio.sleep(CLI_TIMEOUT_CHECK_INTERVAL)
            elapsed = int(loop.time() - start_time)

            # 检查是否超时
            if elapsed >= CLI_EXEC_TIMEOUT and not timed_out:
                timed_out = True
                # 先发送通知告知用户任务已超时，正在收集剩余输出
                try:
                    await safe_edit_text(
                        message,
                        msg("chat", "timeout_collecting", elapsed=elapsed),
                        reply_markup=get_stop_keyboard()
                    )
                except Exception:
                    pass
                # 请求停止读取，但给一些时间收集剩余输出
                stop_reading.set()
                # 先尝试优雅终止，给3秒时间收集输出
                process.terminate()
                # 等待读取线程结束，最多5秒
                reader_thread.join(timeout=5)
                # 如果还在运行，强制终止
                if reader_thread.is_alive() or process.poll() is None:
                    await _terminate_process_tree(process)
                # 继续循环收集队列中的剩余输出
                continue

            # 从队列收集新输出
            while not output_queue.empty():
                try:
                    line = output_queue.get_nowait()
                    output_lines.append(line)
                except queue.Empty:
                    break

            current_time = loop.time()
            time_since_last_update = current_time - last_update_time

            # 定期更新等待提示（超时后更频繁地更新以显示收集进度）
            update_interval = 1 if timed_out else CLI_PROGRESS_UPDATE_INTERVAL
            if time_since_last_update >= update_interval:
                last_update_time = current_time
                try:
                    if timed_out:
                        # 超时后显示已收集的输出长度
                        collected_len = len(''.join(output_lines))
                        status_text = f"⏱️ 已超时（{elapsed}秒），正在收集剩余输出...\n已收集 {collected_len} 字符"
                        await safe_edit_text(message, status_text, reply_markup=get_stop_keyboard())
                    else:
                        collected = ''.join(output_lines)
                        preview = collected[-200:].strip() if collected.strip() else ""
                        if preview:
                            escaped_preview = html.escape(preview)
                            status_text = (
                                f"{msg('chat', 'processing_with_time', elapsed=elapsed)}"
                                f"\n<pre>{escaped_preview}</pre>"
                            )
                            await safe_edit_text(message, status_text, parse_mode="HTML", reply_markup=get_stop_keyboard())
                        else:
                            await safe_edit_text(
                                message,
                                msg("chat", "processing_with_time", elapsed=elapsed),
                                reply_markup=get_stop_keyboard()
                            )
                except Exception:
                    pass

        # 等待读取线程结束
        stop_reading.set()
        if reader_thread.is_alive():
            reader_thread.join(timeout=3)

        # 收集剩余输出
        while not output_queue.empty():
            try:
                line = output_queue.get_nowait()
                output_lines.append(line)
            except queue.Empty:
                break

        raw_output = ''.join(output_lines)
        returncode = await _resolve_process_returncode(process, returncode_container[0])
        was_stopped = _is_stop_requested(session)

        final_text = raw_output if raw_output.strip() else msg("chat", "no_output")
        
        if timed_out:
            final_text = raw_output if raw_output.strip() else msg("chat", "timeout_no_output")
        elif was_stopped:
            final_text = raw_output if raw_output.strip() else msg("chat", "no_output")

        chunks = split_text_into_chunks(final_text, max_len=900)
        if timed_out:
            icon = "⏱️"
        elif was_stopped:
            icon = "🛑"
        else:
            icon = "✅" if returncode == 0 else "⚠️"

        # 删除进度消息，发送最终结果
        try:
            await message.delete()
        except Exception:
            pass

        sent_messages = []
        for i, chunk in enumerate(chunks):
            prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
            is_last = (i == len(chunks) - 1)
            footer = (
                f"\n\n{msg('chat', 'timeout', timeout=CLI_EXEC_TIMEOUT)}"
                f"\n{msg('chat', 'timeout_warning')}"
            ) if (timed_out and is_last) else ""
            formatted = f"{icon} {prefix}<pre>{html.escape(chunk)}</pre>{footer}"
            new_msg = await update.message.reply_text(formatted, parse_mode="HTML")
            sent_messages.append(new_msg)
            await asyncio.sleep(0.3)

        return final_text, returncode, timed_out

    except Exception as e:
        logger.error(f"CLI输出收集错误: {e}")
        stop_reading.set()
        try:
            await safe_edit_text(message, msg("chat", "error", error=str(e)))
        except Exception:
            pass
        return "", -1, False


async def stream_codex_json_output(
    process: subprocess.Popen, update: Update, session=None
) -> Tuple[str, Optional[str], int, bool]:
    """流式读取 codex --json 输出，定期刷新等待提示和已输出内容。
    
    Returns:
        Tuple[str, Optional[str], int, bool]: (输出文本, thread_id, 返回码, 是否因超时而终止)
    """
    loop = asyncio.get_running_loop()
    message = await update.message.reply_text(
        msg("chat", "processing").replace("处理中", "Codex处理中"),
        reply_markup=get_stop_keyboard()
    )
    start_time = loop.time()
    timed_out = False

    # 用于收集输出的队列和列表
    output_queue: queue.Queue[str] = queue.Queue()
    output_lines: List[str] = []
    returncode_container: List[Optional[int]] = [None]
    stop_reading = threading.Event()

    def read_stdout():
        """后台线程：持续读取stdout到队列"""
        try:
            if process.stdout is None:
                return
            # 使用更可靠的方式读取，避免无限阻塞
            import os
            
            stdout = process.stdout
            
            while not stop_reading.is_set():
                line = stdout.readline()
                if not line:
                    # 检查进程是否已结束
                    if process.poll() is not None:
                        break
                    # 短暂休眠避免忙等
                    time.sleep(0.1)
                    continue
                output_queue.put(line)
            
            # 获取返回码
            returncode_container[0] = process.poll()
        except Exception as e:
            logger.warning(f"读取stdout时出错: {e}")

    # 启动后台读取线程
    reader_thread = threading.Thread(target=read_stdout, daemon=True)
    reader_thread.start()

    # 状态跟踪
    last_update_time = 0
    displayed_output_len = 0
    progress_message = message

    try:
        while reader_thread.is_alive() or not output_queue.empty():
            await asyncio.sleep(CLI_TIMEOUT_CHECK_INTERVAL)
            elapsed = int(loop.time() - start_time)

            # 检查是否超时
            if elapsed >= CLI_EXEC_TIMEOUT and not timed_out:
                timed_out = True
                # 先发送通知告知用户任务已超时，正在收集剩余输出
                try:
                    await safe_edit_text(
                        progress_message,
                        f"⏱️ Codex已超时（{elapsed}秒），正在收集剩余输出...",
                        reply_markup=get_stop_keyboard()
                    )
                except Exception:
                    pass
                # 请求停止读取，但给一些时间收集剩余输出
                stop_reading.set()
                # 先尝试优雅终止，给3秒时间收集输出
                process.terminate()
                # 等待读取线程结束，最多5秒
                reader_thread.join(timeout=5)
                # 如果还在运行，强制终止
                if reader_thread.is_alive() or process.poll() is None:
                    await _terminate_process_tree(process)
                # 继续循环收集队列中的剩余输出
                continue

            # 从队列收集新输出
            new_lines = []
            while not output_queue.empty():
                try:
                    line = output_queue.get_nowait()
                    output_lines.append(line)
                    new_lines.append(line)
                except queue.Empty:
                    break

            current_time = loop.time()
            time_since_last_update = current_time - last_update_time

            # 定期更新：每 PROGRESS_UPDATE_INTERVAL 秒更新一次提示和输出
            # 超时后更频繁地更新以显示收集进度
            update_interval = 1 if timed_out else CLI_PROGRESS_UPDATE_INTERVAL
            if time_since_last_update >= update_interval:
                last_update_time = current_time
                
                # 构建显示文本
                full_output = ''.join(output_lines)
                
                # 尝试解析已收集的输出获取有效文本
                preview_text, _ = parse_codex_json_output(full_output)
                if preview_text == msg("chat", "no_output"):
                    preview_text = full_output
                
                # 超时后显示收集进度
                if timed_out:
                    status_text = f"⏱️ 已超时（{elapsed}秒），正在收集剩余输出...\n已收集 {len(full_output)} 字符\n\n"
                else:
                    status_text = msg("chat", "processing_with_time", elapsed=elapsed).replace("处理中", "Codex处理中") + "\n\n"
                
                # 只显示最后一部分（避免消息太长）
                preview = preview_text[-800:] if len(preview_text) > 800 else preview_text
                preview = preview.strip()
                
                if preview and not timed_out:
                    # 转义HTML并截断显示
                    escaped = html.escape(preview)
                    status_text += f"<pre>{escaped}</pre>"
                
                await safe_edit_text(progress_message, status_text, reply_markup=get_stop_keyboard())
                displayed_output_len = len(full_output)

        # 等待读取线程结束
        stop_reading.set()
        if reader_thread.is_alive():
            reader_thread.join(timeout=3)

        # 收集剩余输出
        while not output_queue.empty():
            try:
                line = output_queue.get_nowait()
                output_lines.append(line)
            except queue.Empty:
                break

        raw_output = ''.join(output_lines)
        returncode = await _resolve_process_returncode(process, returncode_container[0])
        was_stopped = _is_stop_requested(session)

        final_text, thread_id = parse_codex_json_output(raw_output)

        if timed_out:
            if not final_text or final_text == msg("chat", "no_output"):
                final_text = msg("chat", "timeout_no_output")
            
            chunks = split_text_into_chunks(final_text, max_len=900)
            icon = "⏱️"
            
            # 删除进度消息，发送最终结果
            try:
                await progress_message.delete()
            except Exception:
                pass

            sent_messages = []
            for i, chunk in enumerate(chunks):
                prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
                is_last = (i == len(chunks) - 1)
                footer = (
                    f"\n\n{msg('chat', 'timeout', timeout=CLI_EXEC_TIMEOUT)}"
                    f"\n{msg('chat', 'timeout_warning')}"
                ) if is_last else ""
                formatted = f"{icon} {prefix}<pre>{html.escape(chunk)}</pre>{footer}"
                new_msg = await update.message.reply_text(formatted, parse_mode="HTML")
                sent_messages.append(new_msg)
                await asyncio.sleep(0.3)

            return final_text, thread_id, returncode, True
        else:
            if not final_text:
                final_text = msg("chat", "no_output")

            chunks = split_text_into_chunks(final_text, max_len=900)
            icon = "🛑" if was_stopped else ("✅" if returncode == 0 else "⚠️")

            # 删除进度消息，发送最终结果
            try:
                await progress_message.delete()
            except Exception:
                pass

            sent_messages = []
            for i, chunk in enumerate(chunks):
                prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
                formatted = f"{icon} {prefix}<pre>{html.escape(chunk)}</pre>"
                new_msg = await update.message.reply_text(formatted, parse_mode="HTML")
                sent_messages.append(new_msg)
                await asyncio.sleep(0.3)

            return final_text, thread_id, returncode, False
    except Exception as e:
        # 区分网络错误和真正的流式处理错误
        if HTTPX_ERRORS and isinstance(e, HTTPX_ERRORS):
            logger.error(f"Telegram 网络连接错误: {e}")
        else:
            logger.error(f"Codex JSON 流式处理错误: {e}")

        # 无论什么错误，先停止读取线程
        stop_reading.set()
        if reader_thread.is_alive():
            reader_thread.join(timeout=3)

        # 收集队列中的剩余输出
        while not output_queue.empty():
            try:
                output_lines.append(output_queue.get_nowait())
            except queue.Empty:
                break

        # 尝试解析已收集的输出，而不是丢弃
        raw_output = ''.join(output_lines)
        returncode = await _resolve_process_returncode(process, returncode_container[0])

        if raw_output.strip():
            final_text, thread_id = parse_codex_json_output(raw_output)
            logger.info(f"流式处理出错但已恢复 {len(raw_output)} 字符的输出")

            # 删除进度消息，发送已收集的结果
            try:
                await progress_message.delete()
            except Exception:
                pass

            # 先发送错误提示，告知用户出了什么问题
            error_type = "网络连接错误" if (HTTPX_ERRORS and isinstance(e, HTTPX_ERRORS)) else "流式处理错误"
            error_notice = f"⚠️ Codex {error_type}: <code>{html.escape(str(e))}</code>\n已恢复已收集的输出："
            try:
                await update.message.reply_text(error_notice, parse_mode="HTML")
            except Exception:
                pass

            chunks = split_text_into_chunks(final_text, max_len=900)
            for i, chunk in enumerate(chunks):
                prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
                formatted = f"⚠️ {prefix}<pre>{html.escape(chunk)}</pre>"
                try:
                    await update.message.reply_text(formatted, parse_mode="HTML")
                except Exception:
                    pass
                await asyncio.sleep(0.3)

            return final_text, thread_id, returncode, False
        else:
            # 真的没有输出，才报错
            try:
                await safe_edit_text(progress_message, msg("chat", "error", error=str(e)))
            except Exception:
                pass
            return "", None, returncode, False


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text_override: str = None):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    profile = get_current_profile(context)
    session = get_current_session(update, context)

    user_text = text_override if text_override is not None else update.message.text
    if user_text.startswith("//"):
        user_text = "/" + user_text[2:]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if sys.platform == "win32":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

    cli_type = normalize_cli_type(profile.cli_type)
    cli_path = profile.cli_path
    resolved_cli = resolve_cli_executable(cli_path, session.working_dir)
    if resolved_cli is None:
        await update.message.reply_text(
            msg("chat", "no_cli", cli_path=cli_path)
        )
        return

    # Codex 需要 CI=true 环境变量来避免 "stdout is not a terminal" 错误
    if cli_type == "codex":
        env["CI"] = "true"

    is_busy = False
    with session._lock:
        if session.is_processing:
            is_busy = True
        else:
            session.is_processing = True
            session.stop_requested = False
            codex_session_id: Optional[str] = None
            cli_session_id: Optional[str] = None
            resume_session = False

            if cli_type == "codex":
                codex_session_id = session.codex_session_id
                cli_session_id = codex_session_id
                resume_session = bool(codex_session_id)
            elif cli_type == "kimi":
                if not session.kimi_session_id:
                    session.kimi_session_id = f"kimi-{uuid.uuid4().hex}"
                cli_session_id = session.kimi_session_id
            elif cli_type == "claude":
                if not session.claude_session_id:
                    session.claude_session_id = str(uuid.uuid4())
                    session.claude_session_initialized = False
                cli_session_id = session.claude_session_id
                resume_session = session.claude_session_initialized

    if is_busy:
        await update.message.reply_text(msg("chat", "busy"), reply_markup=get_stop_keyboard())
        return

    try:
        session.touch()

        full_prompt = user_text

        try:
            cmd, use_stdin = build_cli_command(
                cli_type=cli_type,
                resolved_cli=resolved_cli,
                user_text=full_prompt,
                env=env,
                session_id=cli_session_id,
                resume_session=resume_session,
                json_output=(cli_type == "codex"),
                params_config=profile.cli_params,
            )
        except ValueError as e:
            await update.message.reply_text(msg("chat", "error", error=str(e)))
            return

        session.add_to_history("user", user_text)

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if use_stdin else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=session.working_dir,
                env=env,
                encoding="utf-8",
                errors="replace",
            )

            if use_stdin:
                try:
                    assert process.stdin is not None
                    process.stdin.write(full_prompt + "\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError) as e:
                    logger.error(f"CLI stdin 写入失败: {e}")
                    await update.message.reply_text(msg("chat", "cli_failed"))
                    process.wait()
                    return

            with session._lock:
                session.process = process

            session_id_changed = False
            if cli_type == "codex":
                response, thread_id, returncode, timed_out = await stream_codex_json_output(process, update, session)
                if timed_out:
                    # 超时后保留会话，让用户决定是否继续
                    # 发送提示消息告知用户任务已超时但会话保留
                    pass
                elif thread_id:
                    with session._lock:
                        if session.codex_session_id != thread_id:
                            session.codex_session_id = thread_id
                            session_id_changed = True
                elif should_reset_codex_session(codex_session_id, response, returncode):
                    with session._lock:
                        if session.codex_session_id is not None:
                            session.codex_session_id = None
                            session_id_changed = True
            else:
                response, returncode, timed_out = await collect_cli_output(process, update, session)
                if cli_type == "claude":
                    with session._lock:
                        if timed_out:
                            # 超时后保留会话，让用户决定是否继续
                            pass
                        elif should_mark_claude_session_initialized(response, returncode):
                            if not session.claude_session_initialized:
                                session.claude_session_initialized = True
                                session_id_changed = True
                        elif should_reset_claude_session(response, returncode):
                            if session.claude_session_id is not None:
                                session.claude_session_id = None
                                session.claude_session_initialized = False
                                session_id_changed = True
                elif cli_type == "kimi":
                    with session._lock:
                        if not timed_out and should_reset_kimi_session(response, returncode):
                            if session.kimi_session_id is not None:
                                session.kimi_session_id = None
                                session_id_changed = True
            # 持久化 session_id 变化
            if session_id_changed:
                session.persist()
            session.add_to_history("assistant", response)
        except FileNotFoundError:
            await update.message.reply_text(msg("chat", "no_cli", cli_path=cli_path))
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            await update.message.reply_text(msg("chat", "error", error=str(e)))
    finally:
        with session._lock:
            session.process = None
            session.stop_requested = False
            session.is_processing = False


async def handle_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理停止任务按钮的点击"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not check_auth(user_id):
        await query.edit_message_text("⛔ 未授权的用户")
        return
    
    session = get_current_session(update, context)
    
    with session._lock:
        if not session.is_processing or session.process is None:
            await query.edit_message_text("ℹ️ 任务已经完成或不存在")
            return
        
        session.stop_requested = True
        process = session.process
    
    # 在锁外终止进程（使用改进的终止逻辑）
    try:
        if process.poll() is None:
            await _terminate_process_tree(process)
            await query.edit_message_text("✅ 已强制终止当前任务")
        else:
            await query.edit_message_text("ℹ️ 任务已经完成")
    except Exception as e:
        logger.error(f"终止进程时出错: {e}")
        await query.edit_message_text(f"❌ 终止进程时出错: {e}")
