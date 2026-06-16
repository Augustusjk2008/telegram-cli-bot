from __future__ import annotations

import argparse
from pathlib import Path

from .paths import default_suite_root
from .prepare import prepare_run
from .report import render_report
from .scoring import score_run


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    suite_root = Path(getattr(args, "suite_root", None) or default_suite_root()).resolve()

    if args.command == "prepare":
        paths = prepare_run(
            suite_root=suite_root,
            run_id=args.run,
            preset=args.preset,
            samples=args.samples,
            seed=args.seed,
            overwrite=args.overwrite,
            ifeval_input=Path(args.ifeval_input).resolve() if args.ifeval_input else None,
            simpleqa_csv=Path(args.simpleqa_csv).resolve() if args.simpleqa_csv else None,
            evalplus_source=args.evalplus_source,
            gaia_jsonl=Path(args.gaia_jsonl).resolve() if args.gaia_jsonl else None,
        )
        print(f"已生成: {paths.workspace}")
        print(f"隐藏评分: {paths.gold_dir}")
        return 0

    if args.command == "score":
        score_run(
            suite_root=suite_root,
            run_id=args.run,
            simpleqa_grader=args.simpleqa_grader,
            simpleqa_grader_model=args.simpleqa_grader_model,
            evalplus_timeout=args.evalplus_timeout,
            model=args.model,
        )
        print(f"已评分: {suite_root / 'runs' / args.run / 'report' / 'summary.csv'}")
        return 0

    if args.command == "report":
        report_path = render_report(
            suite_root=suite_root,
            run_id=args.run,
            open_report=args.open,
        )
        print(f"已生成报告: {report_path}")
        return 0

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m suite")
    parser.add_argument("--suite-root", default=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--suite-root", default=argparse.SUPPRESS)
    prepare.add_argument("--run", required=True)
    prepare.add_argument("--preset", default="win-native", choices=["win-native", "win-native-hard", "smoke"])
    prepare.add_argument("--samples", type=int, default=50)
    prepare.add_argument("--seed", type=int, default=20260616)
    prepare.add_argument("--overwrite", action="store_true")
    prepare.add_argument("--ifeval-input")
    prepare.add_argument("--simpleqa-csv")
    prepare.add_argument("--evalplus-source", default="local", choices=["local", "humaneval-plus"])
    prepare.add_argument("--gaia-jsonl")

    score = subparsers.add_parser("score")
    score.add_argument("--suite-root", default=argparse.SUPPRESS)
    score.add_argument("--run", required=True)
    score.add_argument("--simpleqa-grader", default="deterministic", choices=["deterministic", "openai"])
    score.add_argument("--simpleqa-grader-model")
    score.add_argument("--evalplus-timeout", type=float, default=3.0)
    score.add_argument("--model", default="unknown")

    report = subparsers.add_parser("report")
    report.add_argument("--suite-root", default=argparse.SUPPRESS)
    report.add_argument("--run", required=True)
    report.add_argument("--open", action="store_true")
    return parser
