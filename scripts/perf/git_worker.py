from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


def _git(root: Path, *args: str, timeout: float) -> None:
    subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--total-files", type=int, required=True)
    parser.add_argument("--untracked-files", type=int, required=True)
    parser.add_argument("--git-timeout", type=float, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="tcb-perf-git-") as temp_dir:
        root = Path(temp_dir)
        _git(root, "init", "--quiet", timeout=args.git_timeout)
        tracked_count = args.total_files - args.untracked_files
        for index in range(tracked_count):
            path = root / "tracked" / f"bucket-{index // 1000:03d}" / f"file-{index:06d}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"tracked {index}\n", encoding="utf-8")
        if tracked_count:
            _git(root, "add", "tracked", timeout=args.git_timeout)
            _git(
                root,
                "-c",
                "user.name=Perf",
                "-c",
                "user.email=perf@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "baseline",
                timeout=args.git_timeout,
            )
        for index in range(args.untracked_files):
            path = root / "untracked" / f"bucket-{index // 1000:03d}" / f"file-{index:06d}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"untracked {index}\n", encoding="utf-8")

        from bot.web.git_service import get_git_overview

        manager = SimpleNamespace(
            main_profile=SimpleNamespace(alias="perf", working_dir=str(root)),
            managed_profiles={},
        )
        overview = get_git_overview(manager, "perf", 1)
        payload = {
            "duration_seconds": time.monotonic() - started,
            "overview": overview,
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
