from pathlib import Path


def test_start_sh_syncs_python_dependencies_before_env_migration() -> None:
    content = Path("start.sh").read_text(encoding="utf-8")

    python_sync_index = content.index("sync_python_dependencies\n\nif ! \"$PYTHON_BIN\" -m bot.env_migration")
    env_migration_index = content.index("bot.env_migration")

    assert python_sync_index < env_migration_index
    assert '"$PYTHON_BIN" -m pip install -r "$SCRIPT_DIR/requirements.txt"' in content
    assert '"$PYTHON_BIN" -m venv "$SCRIPT_DIR/.venv"' in content


def test_start_sh_resyncs_dependencies_after_pending_update_before_boot() -> None:
    content = Path("start.sh").read_text(encoding="utf-8")

    update_index = content.index("bot.updater apply-pending")
    runtime_sync_index = content.index("sync_runtime_dependencies", update_index)
    migration_index = content.index("bot.migrations run")
    boot_index = content.index('\n  "$PYTHON_BIN" -m bot\n')

    assert update_index < runtime_sync_index < migration_index < boot_index


def test_start_sh_rebuilds_frontend_when_frontend_inputs_change() -> None:
    content = Path("start.sh").read_text(encoding="utf-8")

    assert "front/package-lock.json" in content
    assert "front/src" in content
    assert "front/public" in content
    assert "scripts/build_web_frontend.sh" in content
    assert "frontend-build.sha256" in content
