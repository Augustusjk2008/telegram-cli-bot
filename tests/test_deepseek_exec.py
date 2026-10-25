import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from bot.cli import DeepSeekJsonStreamParser, build_cli_command
from bot.cli_params import CliParamsConfig, get_default_params
from bot.deepseek_cli import build_deepseek_invocation


def deepseek_parser(*events, limit=4096):
    parser = DeepSeekJsonStreamParser(raw_tail_max_bytes=4096, final_text_max_bytes=limit)
    for event in events:
        parser.consume_line(json.dumps(event, ensure_ascii=False) + "\n")
    return parser


SESSION = {"type": "session", "sessionId": "session-test", "cwd": "C:\\workspace"}
COMPLETED = {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}}


@pytest.mark.parametrize("prompt", ["中文输入\n第二行", "/help", "//继续"])
def test_deepseek_uses_stdin_and_only_returned_session_ids(monkeypatch, prompt):
    monkeypatch.setattr("bot.config.CLI_MODEL_OPTIONS", ["gpt-test"])
    monkeypatch.setattr("bot.deepseek_cli.build_executable_invocation", lambda path: [path])
    config = CliParamsConfig()
    assert get_default_params("deepseek") == {
        "model": None,
        "reasoning_effort": None,
        "permission_mode": "workspace-write",
        "extra_args": [],
    }
    config.deepseek["extra_args"] = ["--patch", "C:\\配置 文件\\model.yml"]
    for session_id in (None, "session-returned"):
        command, stdin = build_cli_command(
            "deepseek", "dsh", prompt, {}, config, session_id=session_id,
        )
        expected = ["dsh", "--profile", "headless", "--patch", "C:\\配置 文件\\model.yml", "--json"]
        if session_id:
            expected += ["--session-id", session_id]
        assert command == [*expected, "-"]
        assert stdin is True
        assert prompt not in command
    restored = CliParamsConfig.from_dict(config.to_dict())
    assert restored.deepseek == config.deepseek


@pytest.mark.parametrize("permission_mode", ["workspace-write", "danger-full-access"])
def test_deepseek_permission_mode_is_exported_to_harness_env(permission_mode):
    config = CliParamsConfig.from_dict({"deepseek": {"permission_mode": permission_mode}})
    env = {}

    command, stdin = build_cli_command("deepseek", "dsh", "hello", env, config)

    assert command[-2:] == ["--json", "-"]
    assert stdin is True
    assert env["DSH_PERMISSION_MODE"] == permission_mode


@pytest.fixture
def npm_dsh(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js is required for the Harness launcher regression")
    npm = tmp_path / "npm 中文 #path"
    package = npm / "node_modules" / "@deepseek-ai" / "dsh"
    (package / "lib").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "@deepseek-ai/dsh", "type": "module"}), encoding="utf-8")
    (package / "lib" / "bin.js").write_text('''
import { readFileSync } from 'node:fs';
export async function runCli() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const args = process.argv.slice(2);
  const patchIndex = args.lastIndexOf('--patch');
  const patchPath = patchIndex < 0 ? null : args[patchIndex + 1];
  console.log(JSON.stringify({ args, input, patchPath,
    patch: patchPath ? JSON.parse(readFileSync(patchPath, 'utf8')) : null }));
}
if (import.meta.main) await runCli();
''', encoding="utf-8")
    shim = npm / "dsh.cmd"
    shim.write_text('@node "%~dp0/node_modules/@deepseek-ai/dsh/lib/bin.js" %*', encoding="utf-8")
    return shim, package


@pytest.fixture
def desktop_dsh(tmp_path):
    if os.name != "nt" or not shutil.which("node") or not shutil.which("cmd.exe"):
        pytest.skip("Windows Node.js and cmd.exe are required for the Desktop Harness regression")

    root = tmp_path / "DeepSeek Harness"
    wrapper = root / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd"
    cli = root / "app.asar" / "dsh" / "node_modules" / "@deepseek-ai" / "dsh-desktop-host" / "lib" / "cli.js"
    bundled_node = root / "resources" / "runtime" / "primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
    wrapper.parent.mkdir(parents=True)
    cli.parent.mkdir(parents=True)
    bundled_node.parent.mkdir(parents=True)
    shutil.copyfile(shutil.which("node"), bundled_node)
    shutil.copyfile(shutil.which("node"), root / "DeepSeek Harness.exe")
    cli.write_text(
        """
const fs = require('node:fs');
const args = process.argv.slice(2);
if (args.includes('--dump-config')) {
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] !== '--patch' || index + 1 >= args.length) continue;
    const patch = fs.readFileSync(args[index + 1], 'utf8');
    if (patch.includes('@deepseek-ai/dsh-mcp-client')) {
      process.stderr.write('dsh: patch: entry "orbit-tcb-cluster-mcp" not found\\n');
    }
    index += 1;
  }
  process.stdout.write(`models:
  - id: agent-default-model
    name: '@deepseek-ai/dsh-agent-default-model'
    config:
      provider: deepseek-official
      model: deepseek-flash
      inheritedField: keep-me
`);
} else {
  const patchIndex = args.lastIndexOf('--patch');
  const patchPath = patchIndex < 0 ? null : args[patchIndex + 1];
  const input = fs.readFileSync(0, 'utf8');
  process.stdout.write(JSON.stringify({
    args, input, patchPath,
    patch: patchPath ? JSON.parse(fs.readFileSync(patchPath, 'utf8')) : null,
  }) + '\\n');
}
""",
        encoding="utf-8",
    )
    wrapper.write_text(
        "@echo off\n"
        "setlocal DisableDelayedExpansion\n"
        "set \"ELECTRON_RUN_AS_NODE=1\"\n"
        "\"%~dp0..\\..\\..\\..\\DeepSeek Harness.exe\" --expose-internals \"%~dp0..\\..\\..\\..\\app.asar\\dsh\\node_modules\\@deepseek-ai\\dsh-desktop-host\\lib\\cli.js\" %*\n",
        encoding="utf-8",
    )
    return wrapper


def test_deepseek_npm_entry_runs_once_and_preserves_stdin_and_session(npm_dsh):
    shim, _ = npm_dsh
    cmd, stdin = build_cli_command("deepseek", str(shim), "中文\n继续", {}, CliParamsConfig(), session_id="session-existing")
    run = subprocess.run(cmd, input="中文\n继续".encode("utf-8"), capture_output=True, timeout=15)
    result = json.loads(run.stdout)
    assert run.returncode == 0 and stdin is True
    assert result["args"] == ["--profile", "headless", "--json", "--session-id", "session-existing", "-"]
    assert result["input"] == "中文\n继续"
    assert result["patch"] is None


@pytest.mark.parametrize("selection", [{}, {"model": "none", "reasoning_effort": "none"}])
def test_deepseek_desktop_without_selection_runs_the_real_wrapper(desktop_dsh, selection):
    config = CliParamsConfig.from_dict({"deepseek": selection})
    command, stdin = build_cli_command("deepseek", str(desktop_dsh), "中文输入", {}, config)

    assert stdin is True
    assert command[:4] == ["cmd.exe", "/d", "/c", "@"]
    assert command[4] == str(desktop_dsh)
    assert "deepseek_launch.mjs" not in command
    run = subprocess.run(command, input="中文输入".encode("utf-8"), capture_output=True, timeout=15)
    assert run.returncode == 0, run.stderr.decode("utf-8", errors="replace")
    result = json.loads(run.stdout)
    assert result["args"] == ["--profile", "headless", "--json", "-"]
    assert result["input"] == "中文输入"
    assert result["patch"] is None


def test_deepseek_desktop_selection_uses_dump_config_and_cleans_patch(desktop_dsh, tmp_path):
    user_patch = tmp_path / "cluster patch.json"
    user_patch.write_text(json.dumps([{"id": "cluster", "config": {"enabled": True}}]), encoding="utf-8")
    original = user_patch.read_bytes()
    config = CliParamsConfig.from_dict({
        "deepseek": {
            "model": "deepseek-v4-pro",
            "reasoning_effort": "high",
            "extra_args": ["--patch", str(user_patch)],
        },
    })

    command, stdin = build_cli_command("deepseek", str(desktop_dsh), "hello", {}, config)
    assert stdin is True
    bundled_node = desktop_dsh.parents[4] / "resources" / "runtime" / "primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
    assert command[:3] == [str(bundled_node), str(Path(__file__).parents[1] / "bot" / "deepseek_launch.mjs"), "--desktop"]
    assert command[3] == str(desktop_dsh)

    run = subprocess.run(command, input="hello", capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert run.returncode == 0, run.stderr
    metadata, result = [json.loads(line) for line in run.stdout.splitlines()]
    assert metadata == {"type": "orbit_model", "model": "deepseek-v4-pro"}
    assert result["args"] == [
        "--profile", "headless", "--patch", str(user_patch),
        "--patch", result["patchPath"], "--json", "-",
    ]
    assert result["patch"][0]["config"] == {
        "provider": "deepseek-official",
        "model": "deepseek-v4-pro",
        "inheritedField": "keep-me",
        "reasoningEffort": "high",
    }
    assert not Path(result["patchPath"]).parent.exists()
    assert user_patch.read_bytes() == original


def test_deepseek_desktop_cluster_patch_fails_before_launch(desktop_dsh, tmp_path):
    cluster_patch = tmp_path / "cluster patch.json"
    cluster_patch.write_text(json.dumps([{
        "id": "orbit-tcb-cluster-mcp",
        "name": "@deepseek-ai/dsh-mcp-client",
        "config": {"command": "python"},
    }]), encoding="utf-8")
    config = CliParamsConfig.from_dict({"deepseek": {"extra_args": ["--patch", str(cluster_patch)]}})

    command, stdin = build_cli_command("deepseek", str(desktop_dsh), "hello", {}, config)
    assert stdin is True
    assert "deepseek_launch.mjs" in command[1]
    run = subprocess.run(command, input="hello", capture_output=True, text=True, encoding="utf-8", timeout=15)

    assert run.returncode != 0
    assert "不包含 @deepseek-ai/dsh-mcp-client" in run.stderr


def test_deepseek_desktop_routing_wins_over_adjacent_npm_package(desktop_dsh):
    package = desktop_dsh.parent / "node_modules" / "@deepseek-ai" / "dsh"
    (package / "lib").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "@deepseek-ai/dsh"}), encoding="utf-8")
    (package / "lib" / "bin.js").write_text("", encoding="utf-8")

    command = build_deepseek_invocation(str(desktop_dsh), {"model": "deepseek-flash"})

    bundled_node = desktop_dsh.parents[4] / "resources" / "runtime" / "primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
    assert command[0] == str(bundled_node)
    assert command[2] == "--desktop"
    assert command[3] == str(desktop_dsh)


def test_deepseek_wrapper_can_reference_npm_package_outside_shim_directory(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Harness launcher regression")

    package = tmp_path / "global" / "node_modules" / "@deepseek-ai" / "dsh"
    (package / "lib").mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": "@deepseek-ai/dsh"}),
        encoding="utf-8",
    )
    entry = package / "lib" / "bin.js"
    entry.write_text("", encoding="utf-8")
    shim = tmp_path / "shim" / "dsh.cmd"
    shim.parent.mkdir()
    shim.write_text(f'@node "{entry}" %*', encoding="utf-8")

    command = build_deepseek_invocation(str(shim), {"model": "deepseek-flash"})

    assert command[0] == node
    assert Path(command[2]) == entry.resolve()


def test_deepseek_invalid_package_manifest_does_not_raise_none_get(tmp_path):
    package = tmp_path / "global" / "node_modules" / "@deepseek-ai" / "dsh"
    (package / "lib").mkdir(parents=True)
    (package / "package.json").write_text("null", encoding="utf-8")
    entry = package / "lib" / "bin.js"
    entry.write_text("", encoding="utf-8")
    shim = tmp_path / "shim" / "dsh.cmd"
    shim.parent.mkdir()
    shim.write_text(f'@node "{entry}" %*', encoding="utf-8")

    with pytest.raises(ValueError, match="模型选择需要 npm 安装"):
        build_deepseek_invocation(str(shim), {"model": "deepseek-flash"})


def test_deepseek_wrapper_uses_bundled_node_from_shim(tmp_path):
    package = tmp_path / "global" / "node_modules" / "@deepseek-ai" / "dsh"
    (package / "lib").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "@deepseek-ai/dsh"}), encoding="utf-8")
    entry = package / "lib" / "bin.js"
    entry.write_text("", encoding="utf-8")
    shim = tmp_path / "shim" / "dsh.cmd"
    bundled_node = tmp_path / "runtimes" / "node-v22.23.3-win-x64" / "node.exe"
    bundled_node.parent.mkdir(parents=True)
    bundled_node.write_text("", encoding="utf-8")
    shim.parent.mkdir()
    shim.write_text(
        "@echo off\n"
        "set \"PATH=%~dp0..\\runtimes\\node-v22.23.3-win-x64;%PATH%\"\n"
        f'"%~dp0..\\runtimes\\node-v22.23.3-win-x64\\node.exe" "{entry}" %*',
        encoding="utf-8",
    )

    command = build_deepseek_invocation(str(shim), {"model": "deepseek-flash"})

    assert Path(command[0]) == bundled_node.resolve()


@pytest.mark.parametrize("selection,expected", [
    ({}, {"model": "custom-model", "reasoningEffort": "low"}),
    ({"model": "deepseek-v4-pro"}, {"model": "deepseek-v4-pro", "reasoningEffort": "low"}),
    ({"reasoning_effort": "off"}, {"model": "custom-model", "reasoningEffort": "off"}),
    ({"model": "deepseek-flash", "reasoning_effort": "max"}, {"model": "deepseek-flash", "reasoningEffort": "max"}),
])
def test_deepseek_selection_overlays_preserve_provider_and_cleanup(npm_dsh, tmp_path, selection, expected):
    shim, package = npm_dsh
    for name, source in {
        "dsh-home-paths": "export function resolveDshHome() { return 'test-home'; }",
        "dsh-app-boot": '''
import { readFileSync } from 'node:fs';
export function loadProfile() { return { dir: 'profile', patchPath: 'profile.json' }; }
export function loadOverlayPatches(_, file) { return JSON.parse(readFileSync(file, 'utf8')); }
export function readProfilePatches(_, context) { return context.overlays; }
export function composeEntries([patches]) { return patches; }
''',
    }.items():
        dependency = package / "node_modules" / "@deepseek-ai" / name
        dependency.mkdir(parents=True)
        (dependency / "package.json").write_text(json.dumps({"type": "module", "exports": "./index.js"}), encoding="utf-8")
        (dependency / "index.js").write_text(source, encoding="utf-8")
    inherited = {"provider": "deepseek-account", "model": "custom-model", "reasoningEffort": "low"}
    user_patch = tmp_path / "user model.json"
    user_patch.write_text(json.dumps([{"id": "agent-default-model", "name": "@deepseek-ai/dsh-agent-default-model", "config": inherited}]), encoding="utf-8")
    original = user_patch.read_bytes()
    params = CliParamsConfig.from_dict({"deepseek": {**selection, "extra_args": ["--patch", str(user_patch)]}})
    cmd, _ = build_cli_command("deepseek", str(shim), "hello", {}, params)
    run = subprocess.run(cmd, input="hello", capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert run.returncode == 0, run.stderr
    metadata, result = [json.loads(line) for line in run.stdout.splitlines()]
    assert metadata == {"type": "orbit_model", "model": expected["model"]}
    assert result["patch"][0]["config"] == {**inherited, **expected}
    assert result["args"][:4] == ["--profile", "headless", "--patch", str(user_patch)]
    if selection:
        assert result["args"][-4:] == ["--patch", result["patchPath"], "--json", "-"]
        assert not Path(result["patchPath"]).parent.exists()
    else:
        assert result["patchPath"] == str(user_patch)
    assert user_patch.read_bytes() == original


def test_deepseek_rejects_unsupported_reasoning_before_launch():
    with pytest.raises(ValueError, match="思考深度"):
        build_deepseek_invocation("dsh", {"reasoning_effort": "ultra"})


@pytest.mark.parametrize("extra", [
    ["--profile", "web"], ["--json"], ["--session-id=x"], ["injected task"],
    ["-"], ["--"], ["--patch"], ["--patch", "--help"], ["--model", "expensive"],
])
def test_deepseek_rejects_protocol_and_task_overrides(extra):
    config = CliParamsConfig.from_dict({"deepseek": {"extra_args": extra}})
    with pytest.raises(ValueError, match="DeepSeek Harness"):
        build_cli_command("deepseek", "dsh", "hello", {}, config)


def test_deepseek_final_replaces_committed_preview_and_excludes_process_events():
    parser = deepseek_parser(
        SESSION,
        {"type": "thinking", "text": "private reasoning"},
        {"type": "tool_call", "callId": "call-1", "tool": "read", "input": {"file_path": "probe.txt"}},
        {"type": "tool_result", "callId": "call-1", "status": "completed", "result": "file content"},
        {"type": "text", "text": "early answer", "truncated": True},
        {"type": "future_extension", "data": [1]},
        COMPLETED,
        {"type": "final", "text": "完整最终回答"},
    )
    result = parser.result()
    assert result.final_text == parser.preview_text == "完整最终回答"
    assert result.session_id == "session-test"
    assert result.terminal_status == "completed"
    assert result.error_text is None
    assert result.truncated is True


def test_deepseek_step_usage_is_counted_once_and_missing_fields_stay_absent():
    usage = {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
             "usage": {"inputTokens": 134, "outputTokens": 10, "cacheReadTokens": 6016, "totalTokens": 6160}}
    parser = deepseek_parser(SESSION, usage, usage, COMPLETED, {"type": "final", "text": "ok"})
    assert parser.result().terminal_usage == {
        "input_tokens": 134, "output_tokens": 10, "cache_read_input_tokens": 6016, "total_tokens": 6160,
    }
    assert deepseek_parser(SESSION, COMPLETED, {"type": "final", "text": "ok"}).result().terminal_usage is None


@pytest.mark.parametrize("usage", [None, {}, {"inputTokens": 10, "outputTokens": 1, "cacheReadTokens": -1}])
def test_deepseek_incomplete_step_does_not_produce_a_full_usage_total(usage):
    parser = deepseek_parser(
        SESSION,
        {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
         "usage": {"inputTokens": 10, "outputTokens": 1, "cacheReadTokens": 100}},
        {"type": "status", "phase": "step_end", "turn": 1, "step": 2, "usage": usage},
        COMPLETED,
        {"type": "final", "text": "ok"},
    )
    assert parser.result().terminal_usage is None


@pytest.mark.parametrize("events,fragment", [
    ([SESSION, COMPLETED], "final"),
    ([SESSION, {"type": "final", "text": "ok"}], "结束状态"),
    ([COMPLETED, {"type": "final", "text": "ok"}], "会话 ID"),
    ([SESSION, {"type": "status", "phase": "turn_end", "reason": {"kind": "error", "message": "provider failed"}},
      {"type": "final", "text": "partial"}], "provider failed"),
    ([SESSION, {"type": "error", "message": "session missing"}], "session missing"),
    ([SESSION, COMPLETED, {"type": "final", "text": "ok"}, {"type": "final", "text": "again"}], "final 后"),
])
def test_deepseek_requires_a_valid_terminal_protocol(events, fragment):
    result = deepseek_parser(*events).result()
    assert result.terminal_status == "failed"
    assert fragment in result.error_text


def test_deepseek_invalid_json_never_becomes_a_successful_reply():
    parser = deepseek_parser(SESSION)
    parser.consume_line("a startup log, not a JSON event\n")
    parser.consume_line(json.dumps(COMPLETED))
    parser.consume_line(json.dumps({"type": "final", "text": "partial"}))
    result = parser.result()
    assert result.final_text == "partial"
    assert "无效 JSON" in result.terminal_error
    assert result.terminal_status == "failed"


def test_deepseek_overlong_final_is_an_explicit_failure():
    result = deepseek_parser(SESSION, COMPLETED, {"type": "final", "text": "回复" * 10}, limit=12).result()
    assert result.truncated is True
    assert result.terminal_status == "failed"
    assert "输出限制" in result.error_text

