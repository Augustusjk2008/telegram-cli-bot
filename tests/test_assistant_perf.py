from __future__ import annotations

import json

from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.perf import list_perf_records, write_perf_record


def test_list_perf_records_refreshes_changed_file_without_rescanning_dir(tmp_path, monkeypatch):
    home = bootstrap_assistant_home(tmp_path)
    first = write_perf_record(
        home,
        run_id="run_1",
        bot_alias="assistant1",
        source="web",
        task_mode="default",
        interactive=True,
        user_id=1001,
        status="success",
    )

    initial = list_perf_records(home)

    perf_path = next((home.root / "audit" / "perf").glob("*.json"))
    saved = json.loads(perf_path.read_text(encoding="utf-8"))
    saved["status"] = "error"
    perf_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    perf_dir = home.root / "audit" / "perf"
    original_glob = type(perf_dir).glob
    calls = {"count": 0}

    def tracked_glob(self, pattern):
        if self == perf_dir:
            calls["count"] += 1
        return original_glob(self, pattern)

    monkeypatch.setattr(type(perf_dir), "glob", tracked_glob)

    refreshed = list_perf_records(home)

    assert first["status"] == "success"
    assert initial[0]["status"] == "success"
    assert refreshed[0]["status"] == "error"
    assert calls["count"] == 0
