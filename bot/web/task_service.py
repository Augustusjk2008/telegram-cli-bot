"""Workspace task discovery, execution and problem parsing."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any, AsyncIterator
import re


def _workspace_root(workspace: Path | str) -> Path:
    root = Path(workspace).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("工作目录不存在")
    return root


def _has_python_tests(root: Path) -> bool:
    tests_dir = root / "tests"
    if tests_dir.is_dir() and any(tests_dir.rglob("test_*.py")):
        return True
    return any((root / name).exists() for name in ("pytest.ini", "pyproject.toml", "setup.cfg"))


def _has_python_files(root: Path) -> bool:
    return any(path.is_file() for path in root.rglob("*.py") if not any(part in {"venv", ".venv", "__pycache__"} for part in path.parts))


def discover_tasks(workspace: Path | str) -> dict[str, object]:
    root = _workspace_root(workspace)
    items: list[dict[str, object]] = []

    package_json = root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        scripts = data.get("scripts") if isinstance(data, dict) else {}
        if isinstance(scripts, dict):
            for name, command in scripts.items():
                script_name = str(name)
                items.append({
                    "id": f"npm:{script_name}",
                    "label": f"npm {script_name}",
                    "command": f"npm run {script_name}",
                    "source": "package.json",
                    "detail": str(command),
                })

    if _has_python_tests(root):
        items.append({
            "id": "python:pytest",
            "label": "pytest",
            "command": "python -m pytest",
            "source": "tests",
            "detail": "运行 Python 测试",
        })

    if _has_python_files(root):
        items.append({
            "id": "python:compileall",
            "label": "compileall",
            "command": "python -m compileall .",
            "source": "python",
            "detail": "编译检查 Python 文件",
        })

    if (root / "tsconfig.json").is_file():
        items.append({
            "id": "typescript:tsc",
            "label": "tsc",
            "command": "npx tsc --noEmit",
            "source": "tsconfig.json",
            "detail": "TypeScript 类型检查",
        })

    return {"items": items}


def _normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def parse_problem_lines(output: str) -> list[dict[str, object]]:
    lines = output.splitlines()
    problems: list[dict[str, object]] = []

    tsc_pattern = re.compile(
        r"^(?P<path>.+?)\((?P<line>\d+),(?P<column>\d+)\):\s*"
        r"(?P<severity>error|warning)\s+(?P<code>TS\d+):\s*(?P<message>.*)$",
        re.IGNORECASE,
    )
    compiler_pattern = re.compile(
        r"^(?P<path>.+?):(?P<line>\d+):(?P<column>\d+):\s*"
        r"(?P<severity>error|warning|note):\s*(?P<message>.*)$",
        re.IGNORECASE,
    )
    pytest_pattern = re.compile(
        r"^(?P<path>.+?):(?P<line>\d+):\s*(?P<message>(?:AssertionError|Failed:|E\s+).*)$",
    )
    traceback_pattern = re.compile(r'^\s*File "(?P<path>.+?)", line (?P<line>\d+), in .+$')

    for index, line in enumerate(lines):
        match = tsc_pattern.match(line)
        if match:
            problems.append({
                "path": _normalize_path(match.group("path")),
                "line": int(match.group("line")),
                "column": int(match.group("column")),
                "severity": match.group("severity").lower(),
                "message": f"{match.group('code')}: {match.group('message')}",
                "source": "tsc",
            })
            continue

        match = compiler_pattern.match(line)
        if match:
            severity = match.group("severity").lower()
            problems.append({
                "path": _normalize_path(match.group("path")),
                "line": int(match.group("line")),
                "column": int(match.group("column")),
                "severity": "info" if severity == "note" else severity,
                "message": match.group("message"),
                "source": "compiler",
            })
            continue

        match = pytest_pattern.match(line)
        if match:
            problems.append({
                "path": _normalize_path(match.group("path")),
                "line": int(match.group("line")),
                "column": 1,
                "severity": "error",
                "message": match.group("message").removeprefix("E ").strip(),
                "source": "pytest",
            })
            continue

        match = traceback_pattern.match(line)
        if match:
            next_message = ""
            for candidate in lines[index + 1:index + 4]:
                stripped = candidate.strip()
                if stripped:
                    next_message = stripped
                    break
            problems.append({
                "path": _normalize_path(match.group("path")),
                "line": int(match.group("line")),
                "column": 1,
                "severity": "error",
                "message": next_message or "Python traceback",
                "source": "python",
            })

    return problems


def _task_command(task_id: str) -> list[str]:
    if task_id.startswith("npm:"):
        script = task_id.split(":", 1)[1].strip()
        if not script:
            raise ValueError("任务名称不能为空")
        return ["npm", "run", script]
    if task_id == "python:pytest":
        return [sys.executable, "-m", "pytest"]
    if task_id == "python:compileall":
        return [sys.executable, "-m", "compileall", "."]
    if task_id == "typescript:tsc":
        runner = "npx" if shutil.which("npx") else "tsc"
        return [runner, "tsc", "--noEmit"] if runner == "npx" else [runner, "--noEmit"]
    raise ValueError("未知任务")


async def run_task_stream(workspace: Path | str, task_id: str) -> AsyncIterator[dict[str, object]]:
    root = _workspace_root(workspace)
    try:
        command = _task_command(task_id)
    except ValueError as exc:
        yield {"type": "error", "code": "invalid_task", "message": str(exc)}
        return

    yield {"type": "meta", "task_id": task_id, "command": command}
    output_parts: list[str] = []

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        yield {"type": "error", "code": "task_start_failed", "message": str(exc)}
        return

    assert process.stdout is not None
    while True:
        raw = await process.stdout.readline()
        if not raw:
            break
        text = raw.decode("utf-8", errors="replace")
        output_parts.append(text)
        yield {"type": "log", "text": text.rstrip("\r\n")}

    returncode = await process.wait()
    output = "".join(output_parts)
    problems = parse_problem_lines(output)
    yield {
        "type": "done",
        "task_id": task_id,
        "success": returncode == 0,
        "returncode": returncode,
        "output": output,
        "problems": problems,
    }
