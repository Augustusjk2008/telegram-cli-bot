from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_eval import MemoryEvalCase, run_memory_eval
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput


def test_run_memory_eval_reports_hits_and_stale_recall_rate(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path / "assistant-root")
    store = AssistantMemoryStore(home)
    store.upsert(MemoryRecordInput(
        user_id=1001, scope="user", kind="semantic", source_type="chat", source_ref="cap_1",
        title="语言偏好", summary="默认中文", body="- 默认中文\n- 短输出", tags=["preference"],
        entity_keys=["user:1001", "pref:language"], importance=0.9, confidence=1.0, freshness=0.9,
    ))
    store.upsert(MemoryRecordInput(
        user_id=1001, scope="project", kind="episodic", source_type="dream", source_ref="dream_1",
        title="邮件 cron 根因", summary="pending_run_id 残留 + 重启丢队列", body="- pending_run_id 残留\n- 重启后内存队列丢失",
        tags=["cron", "mail"], entity_keys=["incident:cron"], importance=0.8, confidence=0.9, freshness=0.8,
    ))
    results = run_memory_eval(home, user_id=1001, cases=[
        MemoryEvalCase(query="默认中文", expected_memory_kind="semantic", expected_hit_terms=["默认中文"], must_not_hit_terms=["英文"]),
        MemoryEvalCase(query="pending_run_id", expected_memory_kind="episodic", expected_hit_terms=["pending_run_id 残留"], must_not_hit_terms=["无关旧结论"]),
    ])
    assert results.metrics["hit_at_5"] == 1.0
    assert results.metrics["stale_recall_rate"] == 0.0
    assert Path(results.report_path).is_file()
