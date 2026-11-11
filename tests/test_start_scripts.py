from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from bot.update_state import UpdateStore


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
BASH = shutil.which("bash")


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture
def simulated_install(tmp_path):
    if (ROOT / "runtime/portable_bootstrap.py").is_file():
        pytest.skip("Source launcher simulation requires the source distribution")
    root = tmp_path / "simulated installation"
    (root / "bot").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / ".env").write_text("WEB_ENABLED=true\n")
    for name in ("start.ps1", "start.sh"):
        shutil.copy2(ROOT / name, root / name)
    for name in ("update_runner.py", "update_transaction.py", "update_package.py"):
        shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copy2(ROOT / "bot/update_state.py", root / "bot/update_state.py")
    (root / "bot/runtime_paths.py").write_text("import os\nfrom pathlib import Path\ndef get_update_state_root(root): return Path(os.environ['FAKE_STATE_ROOT'])\n")
    (root / "bot/env_migration.py").write_text("print('fake migration output')\n")
    (root / "bot/migrations.py").write_text("print('fake data migration output')\n")
    (root / "bot/main.py").write_text("")
    (root / "bot/__main__.py").write_text('''
import json, os
from pathlib import Path
from bot.update_state import UpdateStore
root = Path.cwd()
counter = root / 'calls.txt'
number = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(number + 1))
codes = json.loads(os.environ['FAKE_EXIT_CODES'])
code = codes[number] if number < len(codes) else 0
print(f'fake host output exit={code}', flush=True)
assert os.environ['CLI_BRIDGE_UPDATE_PROTOCOL'] == '1'
if code == 76:
    store = UpdateStore(root)
    store.mutate(lambda state: state['job'].update(phase='waiting_restart'))
raise SystemExit(code)
''')
    state_root = tmp_path / "state"
    store = UpdateStore(root, state_root)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    script = snapshot / "update_runner.py"
    script.write_text("import sys\nfrom pathlib import Path\nprint('snapshot handoff output')\nPath(" + repr(str(root / "handoff.json")) + ").write_text(__import__('json').dumps(sys.argv[1:]))\n")
    store.mutate(lambda state: state.update(job={"job_id": "specified-job", "phase": "ready", "runner_path": str(script),
                                                "control_python_executable": sys.executable,
                                                "runner_hashes": {script.name: hashlib.sha256(script.read_bytes()).hexdigest()}}))
    env = dict(os.environ, FAKE_STATE_ROOT=str(state_root), TCB_UPDATE_CONTROL_ROOT=str(tmp_path / "control"),
               TCB_STARTUP_SKIP_DEP_SYNC="1", TCB_STARTUP_SKIP_FRONTEND_BUILD="1", TCB_STARTUP_FORCE_DEP_INSTALL="0",
               CLI_BRIDGE_ALLOW_ROOT="1", PYTHONUTF8="1")
    for key in ("CLI_BRIDGE_UPDATE_STATE_FILE", "CLI_BRIDGE_UPDATE_JOB_ID", "PYTHONPATH"):
        env.pop(key, None)
    return root, store, env


def test_source_launchers_do_not_build_frontend_on_startup():
    for name in ("start.ps1", "start.sh"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "npm run build" not in source
        assert "Sync-FrontendAssets" not in source
        assert "sync_frontend_assets" not in source


def test_service_mode_contract_is_present_in_source_launchers():
    powershell = (ROOT / "start.ps1").read_text(encoding="utf-8-sig")
    shell = (ROOT / "start.sh").read_text(encoding="utf-8")
    assert "ValidateSet(" in powershell and '"service"' in powershell
    assert "CLI_BRIDGE_SERVICE_MODE" in powershell
    assert "-Mode service" in powershell or "Mode -eq" in powershell
    assert "CLI_BRIDGE_SERVICE_MODE" in shell
    assert "WEB_AUTO_OPEN_BROWSER=false" in shell
    assert "TCB_KEEP_AWAKE=false" in shell


def test_task_scheduler_service_helpers_have_dry_run_and_no_secret_arguments():
    install = (ROOT / "scripts/install-service.ps1").read_text(encoding="utf-8")
    uninstall = (ROOT / "scripts/uninstall-service.ps1").read_text(encoding="utf-8")
    status = (ROOT / "scripts/service-status.ps1").read_text(encoding="utf-8")
    assert "WhatIf" in install and "WhatIf" in uninstall
    assert "-ServiceProcess -Mode service" in install
    assert "MultipleInstances IgnoreNew" in install
    assert "RestartCount 3" in install
    assert "Get-ScheduledTaskInfo" in status
    assert "TCB_SERVICE_LOG_PATH" in status
    assert "TELEGRAM_BOT_TOKEN" not in install


@pytest.mark.parametrize("codes", [[0], [75, 0], [76]])
@pytest.mark.parametrize("shell", ["powershell", "bash"])
def test_official_source_entry_runs_simulated_host_and_handoffs(simulated_install, codes, shell, tmp_path):
    root, store, env = simulated_install
    env["FAKE_EXIT_CODES"] = json.dumps(codes)
    if shell == "powershell":
        if not POWERSHELL:
            pytest.skip("PowerShell unavailable")
        command = [POWERSHELL, "-NoProfile", "-File", str(root / "start.ps1"), "-ServiceProcess"]
    else:
        if not BASH:
            pytest.skip("bash unavailable")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        python3 = bin_dir / "python3"
        python3.write_text("#!/usr/bin/env bash\nexec '" + sys.executable.replace("\\", "/").replace("'", "'\\''") + "' \"$@\"\n")
        python3.chmod(0o755)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        command = [BASH, str(root / "start.sh").replace("\\", "/")]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "calls.txt").read_text() == str(len(codes))
    for code in codes:
        assert f"fake host output exit={code}" in result.stdout
    if 76 in codes:
        args = json.loads((root / "handoff.json").read_text())
        assert args[0] == "apply" and args[-2:] == ["--job-id", "specified-job"]
        assert store.read()["job"]["phase"] == "waiting_restart"
    else:
        assert not (root / "handoff.json").exists()
        assert store.read()["job"]["phase"] == "ready"


def _portable_script(tmp_path):
    if not POWERSHELL:
        pytest.skip("PowerShell unavailable")
    package = tmp_path / "portable"
    (package / "runtime").mkdir(parents=True)
    builder = ROOT / ".release-local/portable-win/build-portable.ps1"
    code = f'''
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile({_ps_quote(builder)}, [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
$fn = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-PortableScripts' }}, $true)
Invoke-Expression $fn.Extent.Text
$script:Utf8BomEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $true
$script:Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $false
Write-PortableScripts -PackageRoot {_ps_quote(package)}
'''
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return package / "start.ps1"


def test_generated_portable_module_returns_only_integer_with_stdout(tmp_path):
    code = 76
    script = _portable_script(tmp_path)
    bootstrap = script.parent / "runtime/portable_bootstrap.py"
    bootstrap.write_text(f"print('portable host log output')\nraise SystemExit({code})\n")
    command = f'''
$ast = [System.Management.Automation.Language.Parser]::ParseFile({_ps_quote(script)}, [ref]$null, [ref]$null)
$fn = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-RepoModule' }}, $true)
Invoke-Expression $fn.Extent.Text
$scriptDir = {_ps_quote(script.parent)}
$pythonExe = {_ps_quote(sys.executable)}
$result = Invoke-RepoModule -Module 'bot'
if ($result -isnot [int] -or $result -ne {code}) {{ throw 'Exit code polluted by output' }}
Write-Host "verified=$result"
'''
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "portable host log output" in result.stdout and f"verified={code}" in result.stdout


def test_portable_start_uses_package_storage_locator_after_migration(tmp_path):
    script = _portable_script(tmp_path)
    package = script.parent
    (package / ".tcb").mkdir()
    (package / ".tcb/storage.json").write_text("{}", encoding="utf-8")
    command = f'''
$ast = [System.Management.Automation.Language.Parser]::ParseFile({_ps_quote(script)}, [ref]$null, [ref]$null)
$fn = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Set-PortableRuntimeEnv' }}, $true)
Invoke-Expression $fn.Extent.Text
$env:TCB_DATA_DIR = 'external-override'
Set-PortableRuntimeEnv -PackageRoot {_ps_quote(package)}
Write-Output "portable=$env:TCB_PORTABLE_ROOT"
Write-Output "data=$($env:TCB_DATA_DIR)"
'''
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"portable={package}" in result.stdout
    assert "data=" in result.stdout and "data=external-override" not in result.stdout


def test_portable_recovery_uses_cached_runner_even_when_embedded_python_is_missing(tmp_path):
    script = _portable_script(tmp_path)
    package = script.parent
    pointer_dir = package / ".tcb/startup"
    pointer_dir.mkdir(parents=True)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"job": {"phase": "applying"}}))
    recovery = tmp_path / "recovery.py"
    recovery.write_text("print('independent recovery reached')\n")
    (pointer_dir / "update-launcher.json").write_text(json.dumps({
        "control_python_executable": sys.executable, "runner_path": str(recovery),
        "state_file": str(state_file), "python_executable": str(package / "runtime/python/python.exe")}))
    env = dict(os.environ, TCB_PORTABLE_SKIP_ELEVATE="1")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-File", str(script)], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "independent recovery reached" in result.stdout


def test_first_upgrade_wrapper_waits_for_old_interpreter_to_exit_before_handoff(tmp_path):
    if not POWERSHELL:
        pytest.skip("PowerShell unavailable")
    wrapper = tmp_path / "update_bootstrap.ps1"
    shutil.copy2(ROOT / "scripts/update_bootstrap.ps1", wrapper)
    marker = tmp_path / "old-exited.txt"
    code = "from pathlib import Path; assert Path(" + repr(str(marker)) + ").read_text() == 'closed'; print('new interpreter handoff')"
    # atexit represents the old bootstrap's final cleanup, before the shell starts
    # the replacement interpreter. Both programs are temporary, non-listening hosts.
    (tmp_path / "update_bootstrap.py").write_text(
        "import atexit,json,sys\nfrom pathlib import Path\n"
        + "atexit.register(lambda: Path(" + repr(str(marker)) + ").write_text('closed'))\n"
        + "print(json.dumps({'command': [sys.executable, '-c', " + repr(code) + "]}))\n")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-File", str(wrapper), "-RepoRoot", str(tmp_path),
                             "-Package", "unused.zip", "-Sha256", "unused", "-WorkDir", str(tmp_path / "work"),
                             "-Python", sys.executable], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "new interpreter handoff" in result.stdout


def test_source_recovery_bypasses_damaged_application_imports(simulated_install):
    if not POWERSHELL:
        pytest.skip("PowerShell unavailable")
    root, store, env = simulated_install
    job = store.mutate(lambda state: state["job"].update(phase="applying"))["job"]
    pointer = root / ".tcb/startup"
    pointer.mkdir(parents=True)
    (pointer / "update-launcher.json").write_text(json.dumps({
        "control_python_executable": sys.executable, "runner_path": job["runner_path"],
        "state_file": str(store.state_path), "python_executable": sys.executable}))
    (root / "scripts/update_runner.py").write_text("raise RuntimeError('damaged application')")
    (root / "bot/env_migration.py").write_text("raise RuntimeError('damaged application')")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-File", str(root / "start.ps1"), "-ServiceProcess"],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((root / "handoff.json").read_text())[0] == "supervise"


def test_portable_manifest_creation_records_distribution_identity(tmp_path):
    if not POWERSHELL:
        pytest.skip("PowerShell unavailable")
    builder = ROOT / ".release-local/portable-win/build-portable.ps1"
    package = tmp_path / "package"
    package.mkdir()
    arguments_file = tmp_path / "arguments.json"
    code = f'''
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile({_ps_quote(builder)}, [ref]$null, [ref]$null)
$fn = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-DistributionMarker' }}, $true)
Invoke-Expression $fn.Extent.Text
$script:RepoRoot = {_ps_quote(ROOT)}
function Invoke-CheckedCommand {{
    param($FilePath, $Arguments, $FailureMessage)
    $Arguments | ConvertTo-Json | Set-Content -LiteralPath {_ps_quote(arguments_file)}
}}
Write-DistributionMarker -Root {_ps_quote(package)} -PackageKind 'portable' -Platform 'windows-x64' -Version '2.0.0'
'''
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    arguments = json.loads(arguments_file.read_text(encoding="utf-8-sig"))
    assert arguments[1] == "create"
    marker = json.loads((package / ".distribution.json").read_text(encoding="utf-8-sig"))
    assert marker["packageKind"] == "portable" and marker["version"] == "2.0.0"


def test_windows_launchers_read_state_as_utf8_and_survive_self_replacement():
    # Windows PowerShell 5.1 decodes BOM-less files with the ANSI code page (GBK on
    # Chinese Windows); the update state and runtime files are UTF-8 JSON.
    for relative in ("start.ps1", "scripts/service-status.ps1"):
        text = (ROOT / relative).read_text(encoding="utf-8-sig")
        reads = [line for line in text.splitlines() if "Get-Content" in line and "ConvertFrom-Json" in line]
        assert reads and all("-Encoding UTF8" in line for line in reads), relative
    # cmd.exe re-reads a running batch file by byte offset and an update may replace
    # it: the launch and every later command must sit in one pre-parsed block.
    lines = (ROOT / "start.bat").read_text(encoding="utf-8").splitlines()
    block = lines[max(index for index, line in enumerate(lines) if line.strip() == "("):]
    # The block runs to the end of the file, so nothing is read after the service exits.
    assert block[1].startswith('"%PS_EXE%"') and block[-1].strip() == ")"
    assert any(line.strip().startswith("exit /b") for line in block)
