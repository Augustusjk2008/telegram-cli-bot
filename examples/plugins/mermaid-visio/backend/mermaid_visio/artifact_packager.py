from __future__ import annotations

import io
import json
import zipfile

from .worker_runner import WorkerResult


def package_results(results: list[WorkerResult]) -> tuple[str, bytes, str]:
    successful = [item for item in results if item.ok]
    if len(results) == 1 and len(successful) == 1:
        return successful[0].filename, successful[0].content, "application/vnd.ms-visio.drawing"

    buffer = io.BytesIO()
    report = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for result in results:
            report.append(
                {
                    "filename": result.filename,
                    "ok": result.ok,
                    "warnings": list(result.warnings),
                    "error": result.error,
                }
            )
            if result.ok:
                archive.writestr(result.filename, result.content)
        archive.writestr("conversion-report.json", json.dumps(report, ensure_ascii=False, indent=2))
    return "mermaid-visio-export.zip", buffer.getvalue(), "application/zip"
