from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.perf import FIXED_SEED  # noqa: E402
from scripts.perf.runner import (  # noqa: E402
    RunConfig,
    create_run_directory,
    exit_code_for_status,
    run_serial,
)
from scripts.perf.scenarios import SCENARIO_ORDER  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orbit Safe Claw 固定种子串行性能基线与压力入口")
    parser.add_argument("--scenario", choices=("all", *SCENARIO_ORDER), default="all")
    parser.add_argument("--profile", choices=("baseline", "stress"), default="baseline")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=FIXED_SEED)
    parser.add_argument("--artifact-root", type=Path, default=REPO_ROOT / ".artifacts" / "perf")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--settle-seconds", type=float, default=None)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument("--scenario-timeout", type=float, default=None)
    parser.add_argument("--git-timeout", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.environ.get("TCB_RUN_PERF_BASELINE") != "1":
        print("拒绝运行：请先设置 TCB_RUN_PERF_BASELINE=1，避免误触发重型性能场景。", file=sys.stderr)
        return 2
    is_stress = args.profile == "stress"
    config = RunConfig(
        profile=args.profile,
        seed=args.seed,
        workers=args.workers,
        settle_seconds=args.settle_seconds if args.settle_seconds is not None else (30.0 if is_stress else 5.0),
        sample_interval_seconds=args.sample_interval,
        scenario_timeout_seconds=(
            args.scenario_timeout if args.scenario_timeout is not None else (900.0 if is_stress else 120.0)
        ),
        git_command_timeout_seconds=(
            args.git_timeout if args.git_timeout is not None else (300.0 if is_stress else 30.0)
        ),
    )
    artifact_dir: Path | None = None
    try:
        config.validate()
        artifact_dir = create_run_directory(args.artifact_root, run_id=args.run_id or None)
        names = SCENARIO_ORDER if args.scenario == "all" else (args.scenario,)
        result = asyncio.run(
            run_serial(
                names,
                config=config,
                artifact_dir=artifact_dir,
                command=[sys.executable, *sys.argv],
            )
        )
    except (OSError, ValueError) as exc:
        print(f"性能入口配置失败：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if artifact_dir is not None:
            (artifact_dir / "fatal.json").write_text(
                json.dumps(
                    {"status": "fail", "error": f"{type(exc).__name__}: {exc}"},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        print(f"性能入口失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    status = str(result["status"])
    print(f"性能产物：{artifact_dir}")
    print(f"场景顺序：{', '.join(result['scenario_order'])}")
    print(f"结果：{status.upper()}")
    return exit_code_for_status(status)


if __name__ == "__main__":
    raise SystemExit(main())
