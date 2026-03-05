"""AI CLI 对话处理：进程管理、输出收集、会话续接"""

import asyncio
import html
import logging
import os
import queue
import subprocess
import sys
import threading
import uuid
from typing import List, Optional, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from bot.cli import (
    build_cli_command,
    normalize_cli_type,
    parse_codex_json_output,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
)
from bot.config import CLI_EXEC_TIMEOUT, CLI_PROGRESS_UPDATE_INTERVAL, CLI_TIMEOUT_CHECK_INTERVAL
from bot.context_helpers import get_current_profile, get_current_session
from bot.messages import msg
from bot.utils import check_auth, safe_edit_text, split_text_into_chunks

logger = logging.getLogger(__name__)


async def collect_cli_output(
    process: subprocess.Popen, update: Update, session=None
) -> Tuple[str, int, bool]:
    """运行CLI进程，显示等待提示，最后一次性返回所有输出。
    
    Returns:
        Tuple[str, int, bool]: (输出文本, 返回码, 是否因超时而终止)
    """
    loop = asyncio.get_running_loop()
    message = await update.message.reply_text(msg("chat", "processing"))
    start_time = loop.time()
    timed_out = False

    # 在 executor 中运行进程通信，避免阻塞事件循环
    def run_process():
        try:
            stdout, stderr = process.communicate(timeout=CLI_EXEC_TIMEOUT)
            return stdout or "", process.returncode
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            stdout, _ = process.communicate()
            return stdout or "", process.returncode, True
        except Exception as e:
            logger.error(f"进程通信错误: {e}")
            return "", -1, False

    # 定期更新等待提示的任务
    stop_updating = asyncio.Event()
    last_update_time = [0]

    async def update_progress():
        while not stop_updating.is_set():
            try:
                await asyncio.wait_for(stop_updating.wait(), timeout=CLI_PROGRESS_UPDATE_INTERVAL)
            except asyncio.TimeoutError:
                pass
            if stop_updating.is_set():
                break
            elapsed = int(loop.time() - start_time)
            try:
                await safe_edit_text(message, msg("chat", "processing_with_time", elapsed=elapsed))
                last_update_time[0] = elapsed
            except Exception:
                pass

    # 启动进度更新任务
    progress_task = asyncio.create_task(update_progress())

    try:
        # 在 executor 中运行进程
        result = await loop.run_in_executor(None, run_process)
        if len(result) == 3:
            raw_output, returncode, timed_out = result
        else:
            raw_output, returncode = result
            timed_out = False
    finally:
        stop_updating.set()
        try:
            progress_task.cancel()
            await progress_task
        except asyncio.CancelledError:
            pass

    final_text = raw_output if raw_output.strip() else msg("chat", "no_output")
    
    if timed_out:
        final_text = raw_output if raw_output.strip() else msg("chat", "timeout_no_output")

    chunks = split_text_into_chunks(final_text, max_len=3800)
    icon = "⏱️" if timed_out else ("✅" if returncode == 0 else "⚠️")

    # 删除进度消息，发送最终结果
    try:
        await message.delete()
    except Exception:
        pass

    sent_messages = []
    for i, chunk in enumerate(chunks):
        prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
        formatted = f"{icon} {prefix}<pre>{html.escape(chunk)}</pre>"
        new_msg = await update.message.reply_text(formatted, parse_mode="HTML")
        sent_messages.append(new_msg)
        await asyncio.sleep(0.3)

    if timed_out:
        await update.message.reply_text(
            msg("chat", "timeout", timeout=CLI_EXEC_TIMEOUT),
            parse_mode="HTML"
        )

    return final_text, returncode, timed_out


async def stream_codex_json_output(
    process: subprocess.Popen, update: Update, session=None
) -> Tuple[str, Optional[str], int, bool]:
    """流式读取 codex --json 输出，定期刷新等待提示和已输出内容。
    
    Returns:
        Tuple[str, Optional[str], int, bool]: (输出文本, thread_id, 返回码, 是否因超时而终止)
    """
    loop = asyncio.get_running_loop()
    message = await update.message.reply_text(msg("chat", "processing").replace("处理中", "Codex处理中"))
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
            for line in iter(process.stdout.readline, ''):
                if stop_reading.is_set():
                    break
                if line:
                    output_queue.put(line)
            # 读取完毕后等待进程结束获取返回码
            process.wait()
            returncode_container[0] = process.returncode
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
            if elapsed >= CLI_EXEC_TIMEOUT:
                timed_out = True
                stop_reading.set()
                try:
                    process.terminate()
                    await asyncio.sleep(2)
                    if process.poll() is None:
                        process.kill()
                except Exception as e:
                    logger.warning(f"终止超时进程时出错: {e}")
                break

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
            if time_since_last_update >= CLI_PROGRESS_UPDATE_INTERVAL:
                last_update_time = current_time
                
                # 构建显示文本
                full_output = ''.join(output_lines)
                
                # 尝试解析已收集的输出获取有效文本
                preview_text, _ = parse_codex_json_output(full_output)
                if preview_text == msg("chat", "no_output"):
                    preview_text = full_output
                
                # 只显示最后一部分（避免消息太长）
                preview = preview_text[-800:] if len(preview_text) > 800 else preview_text
                preview = preview.strip()
                
                status_text = msg("chat", "processing_with_time", elapsed=elapsed).replace("处理中", "Codex处理中") + "\n\n"
                if preview:
                    # 转义HTML并截断显示
                    escaped = html.escape(preview)
                    status_text += f"<pre>{escaped}</pre>"
                
                await safe_edit_text(progress_message, status_text)
                displayed_output_len = len(full_output)

        # 等待读取线程结束
        stop_reading.set()
        if reader_thread.is_alive():
            reader_thread.join(timeout=5)

        # 收集剩余输出
        while not output_queue.empty():
            try:
                line = output_queue.get_nowait()
                output_lines.append(line)
            except queue.Empty:
                break

        raw_output = ''.join(output_lines)
        returncode = returncode_container[0] if returncode_container[0] is not None else -1

        final_text, thread_id = parse_codex_json_output(raw_output)

        if timed_out:
            if not final_text or final_text == msg("chat", "no_output"):
                final_text = msg("chat", "timeout_no_output")
            
            chunks = split_text_into_chunks(final_text, max_len=3800)
            icon = "⏱️"
            
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
            
            # 发送超时提示
            await update.message.reply_text(
                msg("chat", "timeout", timeout=CLI_EXEC_TIMEOUT),
                parse_mode="HTML"
            )
            
            return final_text, thread_id, returncode, True
        else:
            if not final_text:
                final_text = msg("chat", "no_output")

            chunks = split_text_into_chunks(final_text, max_len=3800)
            icon = "✅" if returncode == 0 else "⚠️"

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
        logger.error(f"Codex JSON 流式处理错误: {e}")
        await safe_edit_text(progress_message, msg("chat", "error", error=str(e)))
        stop_reading.set()
        return "", None, -1, False


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    profile = get_current_profile(context)
    session = get_current_session(update, context)

    user_text = update.message.text
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
        await update.message.reply_text(msg("chat", "busy"))
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

            if cli_type == "codex":
                response, thread_id, returncode, timed_out = await stream_codex_json_output(process, update, session)
                if timed_out:
                    # 超时后重置会话，下次将创建新会话
                    with session._lock:
                        session.codex_session_id = None
                elif thread_id:
                    with session._lock:
                        session.codex_session_id = thread_id
                elif should_reset_codex_session(codex_session_id, response, returncode):
                    with session._lock:
                        session.codex_session_id = None
            else:
                response, returncode, timed_out = await collect_cli_output(process, update, session)
                if cli_type == "claude":
                    with session._lock:
                        if timed_out:
                            # 超时后重置会话
                            session.claude_session_id = None
                            session.claude_session_initialized = False
                        elif should_mark_claude_session_initialized(response, returncode):
                            session.claude_session_initialized = True
                        elif should_reset_claude_session(response, returncode):
                            session.claude_session_id = None
                            session.claude_session_initialized = False
            session.add_to_history("assistant", response)
        except FileNotFoundError:
            await update.message.reply_text(msg("chat", "no_cli", cli_path=cli_path))
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            await update.message.reply_text(msg("chat", "error", error=str(e)))
    finally:
        with session._lock:
            session.process = None
            session.is_processing = False
