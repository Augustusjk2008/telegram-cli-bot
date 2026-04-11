"""Cross-platform process group helpers."""

import os
import signal
import subprocess


def build_subprocess_group_kwargs() -> dict:
    if os.name == "nt":
        return {}
    return {"start_new_session": True}


def terminate_process_tree_sync(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    if os.name != "nt" and process.pid:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
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

    if os.name == "nt" and process.pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=5,
                check=False,
            )
            process.wait(timeout=2)
            return
        except Exception:
            pass

    process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
