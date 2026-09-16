from __future__ import annotations

import json
from pathlib import Path

from bot.native_agent.config_store import _read_json_object


def test_read_json_object_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"backend": "pi"}).encode("utf-8"))

    assert _read_json_object(path, "settings", default={}) == {"backend": "pi"}
