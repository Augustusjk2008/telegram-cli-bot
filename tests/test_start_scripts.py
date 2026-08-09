from pathlib import Path


def _between(content: str, start: str, end: str) -> str:
    start_index = content.index(start)
    end_index = content.index(end, start_index)
    return content[start_index:end_index]


def test_start_sh_repairs_python_dependencies_only_after_startup_step_fails() -> None:
    content = Path("start.sh").read_text(encoding="utf-8")
    sync = _between(
        content,
        "sync_python_dependencies() {",
        "\npython_dependency_repair_attempted=0",
    )
    helper = _between(
        content,
        "run_python_startup_step() {",
        "\nsync_frontend_assets() {",
    )

    first_attempt_index = helper.index("run_current_python")
    restart_guard_index = helper.index('"$last_python_exit_code" -eq 75')
    repair_index = helper.index("repair_python_dependencies")
    retry_index = helper.index("run_current_python", repair_index)

    assert first_attempt_index < restart_guard_index < repair_index < retry_index
    assert "python_dependency_repair_attempted" in helper
    assert "sync_python_dependencies 1" in content
    repair = _between(
        content,
        "repair_python_dependencies() {",
        "\nrun_python_startup_step() {",
    )
    assert "last_python_exit_code=$?" in repair
    assert sync.count("pip_exit_code=$?") == 2
    assert sync.count('return "$pip_exit_code"') == 2
    assert 'run_python_startup_step -m bot.env_migration --env-path "$SCRIPT_DIR/.env"' in content
    assert 'run_python_startup_step -c "import bot.updater"' in content
    assert 'run_python_startup_step -m bot.migrations run --repo-root "$SCRIPT_DIR"' in content
    assert 'run_python_startup_step -c "import bot.main"' in content
    assert '\n  "$PYTHON_BIN" -m bot --tcb-migrations-checked\n' in content


def test_start_sh_rebuilds_frontend_after_pending_update_without_eager_dependency_sync() -> None:
    content = Path("start.sh").read_text(encoding="utf-8")
    main = content[content.index('if is_truthy "${TCB_STARTUP_FORCE_DEP_INSTALL:-}"; then') :]

    update_index = main.index("bot.updater apply-pending")
    frontend_build_index = main.index("sync_frontend_assets", update_index)
    migration_index = main.index("bot.migrations run")
    import_check_index = main.index('run_python_startup_step -c "import bot.main"')
    boot_index = main.index('\n  "$PYTHON_BIN" -m bot --tcb-migrations-checked\n')

    assert update_index < frontend_build_index < migration_index < import_check_index < boot_index
    assert "sync_runtime_dependencies" not in main
    force_install_indexes = [
        index
        for index in range(len(main))
        if main.startswith("sync_python_dependencies 1", index)
    ]
    assert len(force_install_indexes) == 2
    assert force_install_indexes[0] < update_index < force_install_indexes[1] < frontend_build_index


def test_start_ps1_repairs_python_dependencies_only_after_startup_step_fails() -> None:
    content = Path("start.ps1").read_text(encoding="utf-8")
    helper = _between(
        content,
        "function Invoke-PythonStartupStep {",
        "\nfunction Sync-FrontendAssets {",
    )

    first_attempt_index = helper.index("Invoke-CurrentPython")
    restart_guard_index = helper.index("$script:lastPythonExitCode -eq $restartExitCode")
    repair_index = helper.index("Repair-PythonDependencies")
    retry_index = helper.index("Invoke-CurrentPython", repair_index)

    assert first_attempt_index < restart_guard_index < repair_index < retry_index
    assert "$script:pythonDependencyRepairAttempted" in helper
    assert "-ForceInstall" in helper
    assert 'Invoke-PythonStartupStep -Arguments @("-m", "bot.env_migration"' in content
    assert 'Invoke-PythonStartupStep -Arguments @("-c", "import bot.updater")' in content
    assert 'Invoke-PythonStartupStep -Arguments @("-m", "bot.migrations"' in content
    assert 'Invoke-PythonStartupStep -Arguments @("-c", "import bot.main")' in content
    assert (
        '& $script:pythonRuntime.Command '
        '@($script:pythonRuntime.Arguments + @("-m", "bot", "--tcb-migrations-checked"))'
    ) in content


def test_start_ps1_rebuilds_frontend_after_pending_update_without_eager_dependency_sync() -> None:
    content = Path("start.ps1").read_text(encoding="utf-8")
    main = content[content.index("$script:pythonRuntime = $pythonRuntime") :]

    update_index = main.index('"bot.updater", "apply-pending"')
    frontend_build_index = main.index("Sync-FrontendAssets", update_index)
    migration_index = main.index('"bot.migrations", "run"')
    import_check_index = main.index('Invoke-PythonStartupStep -Arguments @("-c", "import bot.main")')
    boot_index = main.index('@("-m", "bot", "--tcb-migrations-checked")')

    assert update_index < frontend_build_index < migration_index < import_check_index < boot_index
    assert "Sync-RuntimeDependencies" not in main
    force_install_indexes = [
        index
        for index in range(len(main))
        if main.startswith("-ForceInstall", index)
    ]
    assert len(force_install_indexes) == 2
    assert force_install_indexes[0] < update_index < force_install_indexes[1] < frontend_build_index


def test_start_ps1_prefers_existing_project_venv_before_system_python() -> None:
    content = Path("start.ps1").read_text(encoding="utf-8")
    main = content[content.index("try {\n    Set-Location $scriptDir") :]

    venv_lookup_index = main.index("Get-ProjectVenvPythonPath")
    system_lookup_index = main.index("Get-PythonRuntime", venv_lookup_index)
    runtime_assignment_index = main.index("$script:pythonRuntime = $pythonRuntime", system_lookup_index)

    assert venv_lookup_index < system_lookup_index < runtime_assignment_index


def test_frontend_precompression_script_is_part_of_build_and_startup_hashes() -> None:
    package = Path("front/package.json").read_text(encoding="utf-8")
    powershell = Path("start.ps1").read_text(encoding="utf-8")
    shell = Path("start.sh").read_text(encoding="utf-8")

    build_command = 'vite build && node scripts/precompress-assets.mjs && node scripts/check-build-budget.mjs'
    assert build_command in package
    assert powershell.count('"front\\scripts\\precompress-assets.mjs"') == 1
    assert shell.count("front/scripts/precompress-assets.mjs") == 2


def test_start_bat_retries_after_windows_service_failure_instead_of_exiting() -> None:
    content = Path("start.bat").read_text(encoding="utf-8")

    start_label_index = content.index(":START_SERVICE")
    launch_index = content.index('"%PS_EXE%" -NoProfile', start_label_index)
    failure_index = content.index('if not "%EXIT_CODE%"=="0"', launch_index)
    pause_index = content.index("pause", failure_index)
    retry_index = content.index("goto START_SERVICE", pause_index)
    success_exit_index = content.index("exit /b 0", retry_index)

    assert start_label_index < launch_index < failure_index < pause_index < retry_index < success_exit_index
    assert "exit /b %EXIT_CODE%" not in content[failure_index:]
    assert content.index('set "ERRORLEVEL="') < start_label_index

