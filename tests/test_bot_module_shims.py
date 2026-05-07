from __future__ import annotations

import importlib

import pytest


REMOVED_MODULES = [
    "bot.assistant_admin_audit",
    "bot.assistant_compaction",
    "bot.assistant_context",
    "bot.assistant_cron",
    "bot.assistant_cron_store",
    "bot.assistant_cron_types",
    "bot.assistant_diagnostics",
    "bot.assistant_docs",
    "bot.assistant_dream",
    "bot.assistant_dream_managed_context",
    "bot.assistant_home",
    "bot.assistant_knowledge_indexer",
    "bot.assistant_memory_cli",
    "bot.assistant_memory_eval",
    "bot.assistant_memory_maintenance",
    "bot.assistant_memory_recall",
    "bot.assistant_memory_store",
    "bot.assistant_memory_writer",
    "bot.assistant_patch_generation",
    "bot.assistant_perf",
    "bot.assistant_proposals",
    "bot.assistant_runtime",
    "bot.assistant_state",
    "bot.assistant_upgrade",
    "bot.assistant_upgrade_diff",
    "bot.assistant_upgrade_targets",
    "bot.assistant_working_memory_indexer",
    "bot.cluster_config",
    "bot.cluster_mcp_client",
    "bot.cluster_mcp_stdio",
    "bot.cluster_runtime",
    "bot.cluster_setup",
]


@pytest.mark.parametrize("name", REMOVED_MODULES)
def test_legacy_shim_module_is_removed(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)
