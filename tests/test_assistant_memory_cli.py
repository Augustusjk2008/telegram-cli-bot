import json
from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_cli import run_cli
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput


def test_memory_cli_search_outputs_json(tmp_path: Path, capsys):
    home = bootstrap_assistant_home(tmp_path)
    AssistantMemoryStore(home).upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_1",
            title="默认语言",
            summary="默认中文",
            body="- 默认中文回复",
            tags=["preference"],
            entity_keys=["user:1001"],
        )
    )

    code = run_cli(["--workdir", str(tmp_path), "search", "--user-id", "1001", "--query", "默认中文"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["items"][0]["title"] == "默认语言"


def test_memory_cli_invalidate_hides_memory(tmp_path: Path, capsys):
    home = bootstrap_assistant_home(tmp_path)
    memory_id = AssistantMemoryStore(home).upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_2",
            title="过期偏好",
            summary="默认英文",
            body="- 默认英文",
            tags=["preference"],
            entity_keys=["user:1001"],
        )
    )

    code = run_cli(["--workdir", str(tmp_path), "invalidate", "--memory-id", memory_id, "--reason", "user_changed"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["invalidated"] == memory_id
    rows = AssistantMemoryStore(home).search_lexical(user_id=1001, query_text="默认英文")
    assert rows == []


def test_memory_cli_eval_writes_report(tmp_path: Path, capsys):
    home = bootstrap_assistant_home(tmp_path)
    AssistantMemoryStore(home).upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_3",
            title="默认语言",
            summary="默认中文",
            body="- 默认中文",
            tags=["preference"],
            entity_keys=["user:1001"],
        )
    )
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "query": "默认中文",
                        "expected_memory_kind": "semantic",
                        "expected_hit_terms": ["默认中文"],
                        "must_not_hit_terms": ["默认英文"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    code = run_cli(["--workdir", str(tmp_path), "eval", "--user-id", "1001", "--cases", str(cases_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metrics"]["hit_at_5"] == 1.0
    assert payload["metrics"]["stale_recall_rate"] == 0.0
    assert payload["report_path"].endswith(".json")
