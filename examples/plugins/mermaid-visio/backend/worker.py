from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from mermaid_visio.converter import convert_source_to_vsdx
from mermaid_visio.models import DiagramSource, PluginConfig


def main() -> int:
    payload = json.loads(sys.stdin.read())
    source = DiagramSource(**payload["source"])
    config = PluginConfig(**payload["config"])
    handle = tempfile.NamedTemporaryFile(prefix="mermaid-visio-", suffix=f"-{source.suggested_filename}", delete=False)
    output = Path(handle.name)
    handle.close()
    warnings = convert_source_to_vsdx(source, config, output)
    sys.stdout.write(
        json.dumps(
            {
                "ok": True,
                "outputPath": str(output),
                "filename": source.suggested_filename,
                "warnings": warnings,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(0)
