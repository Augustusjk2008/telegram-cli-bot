"""Cross-platform process group helpers."""

import os
import signal
import subprocess


def build_subprocess_group_kwargs() -> dict:
    if os.name == "nt":
        return {}
    return {"start_new_session": True}


def build_chat_cli_process_kwargs() -> dict:
    if os.name != "nt":
        return {"start_new_session": True}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        0,
    )
    if not creationflags:
        return {}
    return {"creationflags": creationflags}


def build_hidden_process_kwargs() -> dict:
    if os.name != "nt":
        return {}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not creationflags:
        return {}
    return {"creationflags": creationflags}


def terminate_process_tree_sync(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    process_pid = getattr(process, "pid", None)
    if os.name == "nt" and process_pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process_pid)],
                capture_output=True,
                timeout=5,
                check=False,
            )
            process.wait(timeout=2)
            return
        except Exception:
            pass

    if os.name != "nt" and process_pid:
        try:
            os.killpg(process_pid, signal.SIGTERM)
            process.wait(timeout=3)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process_pid, signal.SIGKILL)
                process.wait(timeout=2)
                return
            except ProcessLookupError:
                return
            except Exception:
                pass
        except Exception:
            pass

    process.terminate()
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass

    process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
