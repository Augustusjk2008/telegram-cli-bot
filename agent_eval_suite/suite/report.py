from __future__ import annotations

import html
import json
import os
import webbrowser
from pathlib import Path
from typing import Any

from .paths import SuitePaths


def render_report(
    *,
    suite_root: Path,
    run_id: str,
    open_report: bool = False,
) -> Path:
    paths = SuitePaths(suite_root=suite_root.resolve(), run_id=run_id)
    results_path = paths.report_dir / "results.json"
    if not results_path.exists():
        raise FileNotFoundError(f"missing score output: {results_path}")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    html_text = _render_html(paths, results)
    report_path = paths.report_dir / "report.html"
    report_path.write_text(html_text, encoding="utf-8", newline="\n")
    if open_report:
        _open(report_path)
    return report_path


def _render_html(paths: SuitePaths, results: dict[str, Any]) -> str:
    metadata = results.get("metadata", {})
    sections = [_metadata_section(metadata), _summary_section(results), _details_section(paths, results)]
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Eval Report</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#172033;background:#f7f8fb}
main{max-width:1120px;margin:0 auto}
h1,h2{margin:0 0 16px}
section{margin:0 0 28px}
table{border-collapse:collapse;width:100%;background:white;border:1px solid #d9deea}
th,td{padding:8px 10px;border-bottom:1px solid #e8ebf2;text-align:left;vertical-align:top}
th{background:#eef2f8}
.pass{color:#126b39;font-weight:600}.fail{color:#a32626;font-weight:600}
code{font-family:Consolas,monospace}
</style>
</head>
<body><main>
<h1>Agent Eval Report</h1>
""" + "\n".join(sections) + "\n</main></body></html>\n"


def _metadata_section(metadata: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in metadata.items()
        if key != "benchmarks"
    )
    return f"<section><h2>Run</h2><table>{rows}</table></section>"


def _summary_section(results: dict[str, Any]) -> str:
    rows: list[str] = []
    for benchmark, result in results.get("benchmarks", {}).items():
        for metric, value in result.get("metrics", {}).items():
            rows.append(
                "<tr>"
                f"<td>{html.escape(benchmark)}</td>"
                f"<td>{html.escape(metric)}</td>"
                f"<td>{_format_value(value.get('value', 0))}</td>"
                f"<td>{html.escape(str(value.get('passed', 0)))}</td>"
                f"<td>{html.escape(str(value.get('total', 0)))}</td>"
                "</tr>"
            )
    integrity = results.get("workspace_integrity", {})
    status = "pass" if integrity.get("passed") else "fail"
    rows.append(
        "<tr>"
        "<td>workspace</td><td>no_gold_or_hidden_tests</td>"
        f"<td class=\"{status}\">{status}</td><td>{1 if integrity.get('passed') else 0}</td><td>1</td>"
        "</tr>"
    )
    return (
        "<section><h2>Summary</h2><table><tr><th>Benchmark</th><th>Metric</th>"
        "<th>Value</th><th>Passed / Count</th><th>Total</th></tr>"
        + "".join(rows)
        + "</table></section>"
    )


def _details_section(paths: SuitePaths, results: dict[str, Any]) -> str:
    sections: list[str] = []
    for benchmark, result in results.get("benchmarks", {}).items():
        answer_href = _relative_href(paths.report_dir, paths.answers_dir / f"{benchmark}.jsonl")
        rows = []
        for detail in result.get("details", []):
            task_id = detail.get("id") or detail.get("task_id") or ""
            passed = bool(detail.get("passed"))
            status = "pass" if passed else "fail"
            reason = _detail_reason(detail)
            rows.append(
                "<tr>"
                f"<td><code>{html.escape(str(task_id))}</code></td>"
                f"<td class=\"{status}\">{status}</td>"
                f"<td>{html.escape(reason)}</td>"
                f"<td><a href=\"{answer_href}\">answer</a></td>"
                "</tr>"
            )
        sections.append(
            f"<section><h2>{html.escape(benchmark)}</h2>"
            + _schema_errors_table(result.get("schema_errors", []))
            + "<table><tr><th>Task</th><th>Status</th><th>Reason</th><th>Raw</th></tr>"
            + "".join(rows)
            + "</table></section>"
        )
    return "".join(sections)


def _schema_errors_table(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(error.get('line', '')))}</td>"
        f"<td><code>{html.escape(str(error.get('id', '')))}</code></td>"
        f"<td>{html.escape(str(error.get('reason', '')))}</td>"
        "</tr>"
        for error in errors
    )
    return (
        "<p class=\"fail\">Schema errors</p>"
        "<table><tr><th>Line</th><th>ID</th><th>Reason</th></tr>"
        + rows
        + "</table>"
    )


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return html.escape(str(value))


def _detail_reason(detail: dict[str, Any]) -> str:
    reason = str(detail.get("reason", ""))
    failed_checks = detail.get("failed_checks")
    if not failed_checks:
        return reason
    parts = []
    for check in failed_checks:
        check_type = str(check.get("type", ""))
        check_reason = str(check.get("reason", ""))
        path = str(check.get("path", ""))
        parts.append(":".join(part for part in (check_type, path, check_reason) if part))
    suffix = "; ".join(parts)
    if len(suffix) > 300:
        suffix = suffix[:300] + "..."
    return f"{reason} | failed_checks: {suffix}"


def _relative_href(base: Path, target: Path) -> str:
    return html.escape(os.path.relpath(target, start=base).replace(os.sep, "/"))


def _open(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        webbrowser.open(path.resolve().as_uri())
