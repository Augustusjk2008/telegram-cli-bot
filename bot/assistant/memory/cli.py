from __future__ import annotations

import argparse
import json
from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_eval import MemoryEvalCase, run_memory_eval
from bot.assistant_memory_recall import recall_assistant_memories
from bot.assistant_memory_store import AssistantMemoryStore


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_eval_cases(path: Path) -> list[MemoryEvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("eval cases must be a list or an object with cases")
    return [
        MemoryEvalCase(
            query=str(row["query"]),
            expected_memory_kind=str(row["expected_memory_kind"]),
            expected_hit_terms=[str(item) for item in row.get("expected_hit_terms", [])],
            must_not_hit_terms=[str(item) for item in row.get("must_not_hit_terms", [])],
        )
        for row in rows
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assistant-memory")
    parser.add_argument("--workdir", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search")
    search.add_argument("--user-id", type=int, required=True)
    search.add_argument("--query", required=True)

    invalidate = subparsers.add_parser("invalidate")
    invalidate.add_argument("--memory-id", required=True)
    invalidate.add_argument("--reason", required=True)

    eval_parser = subparsers.add_parser("eval")
    eval_parser.add_argument("--user-id", type=int, required=True)
    eval_parser.add_argument("--cases", required=True)
    return parser


def run_cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = bootstrap_assistant_home(args.workdir)

    if args.command == "search":
        recall = recall_assistant_memories(
            home,
            user_id=args.user_id,
            user_text=args.query,
            write_audit=False,
        )
        _print_json(
            {
                "items": [item.__dict__ for item in recall.items],
                "prompt_block": recall.prompt_block,
            }
        )
        return 0

    if args.command == "invalidate":
        AssistantMemoryStore(home).invalidate(args.memory_id, reason=args.reason)
        _print_json({"invalidated": args.memory_id, "reason": args.reason})
        return 0

    if args.command == "eval":
        run = run_memory_eval(
            home,
            user_id=args.user_id,
            cases=_load_eval_cases(Path(args.cases)),
        )
        _print_json({"metrics": run.metrics, "report_path": run.report_path})
        return 0

    raise AssertionError(f"unknown command: {args.command}")


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
