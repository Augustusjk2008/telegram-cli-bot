from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


BENCHMARKS = ("ifeval", "simpleqa", "evalplus", "gaia")


@dataclass(frozen=True)
class SuitePaths:
    suite_root: Path
    run_id: str

    @property
    def run_root(self) -> Path:
        return self.suite_root / "runs" / self.run_id

    @property
    def workspace(self) -> Path:
        return self.run_root / "workspace"

    @property
    def tasks_dir(self) -> Path:
        return self.workspace / "tasks"

    @property
    def answers_dir(self) -> Path:
        return self.workspace / "answers"

    @property
    def report_dir(self) -> Path:
        return self.run_root / "report"

    @property
    def gold_dir(self) -> Path:
        return self.suite_root / "private_gold" / self.run_id

    @property
    def prompt_path(self) -> Path:
        return self.workspace / "PROMPT.md"

    @property
    def metadata_path(self) -> Path:
        return self.run_root / "run.json"

    @property
    def manifest_path(self) -> Path:
        return self.run_root / "manifest.json"


def default_suite_root() -> Path:
    return Path(__file__).resolve().parents[1]
