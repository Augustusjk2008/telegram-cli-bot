import json
import os
import subprocess
import sys

import pytest

from bot.cli import _build_codex_status_terminal_argv
from bot.cli_params import build_codex_project_trust_config_arg
from bot.platform.executables import build_executable_invocation


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows cmd quoting")


@pytest.fixture(params=[".cmd", ".bat"])
def batch_cli(tmp_path, request):
    cli_dir = tmp_path / "Program Files" / "cli"
    cli_dir.mkdir(parents=True)
    (cli_dir / "probe.py").write_text(
        "import json, sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'stdin': sys.stdin.read()}))\n",
        encoding="utf-8",
    )
    wrapper = cli_dir / f"cli{request.param}"
    wrapper.write_text(
        f'@echo off\n"{sys.executable}" "%~dp0probe.py" %*\n',
        encoding="utf-8",
    )
    return wrapper


def test_batch_cli_preserves_spaced_paths_and_arguments(batch_cli, tmp_path):
    workspace = tmp_path / "Project Files"
    workspace.mkdir()
    arguments = ["hello world", str(workspace), 'setting="quoted value"', ""]

    result = subprocess.run(
        [*build_executable_invocation(str(batch_cli)), *arguments],
        cwd=workspace,
        input="hello from stdin",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"args": arguments, "stdin": "hello from stdin"}


def test_codex_status_batch_cli_preserves_spaced_trust_path(batch_cli, tmp_path):
    workspace = tmp_path / "Project Files"
    workspace.mkdir()
    arguments = ["-c", build_codex_project_trust_config_arg(str(workspace)), "--no-alt-screen"]

    result = subprocess.run(
        _build_codex_status_terminal_argv(str(batch_cli), str(workspace)),
        cwd=workspace,
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["args"] == arguments
