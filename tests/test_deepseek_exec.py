import json
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
    assert get_default_params("deepseek") == {"model": None, "reasoning_effort": None, "extra_args": []}
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


def test_deepseek_npm_entry_runs_once_and_preserves_stdin_and_session(npm_dsh):
    shim, _ = npm_dsh
    cmd, stdin = build_cli_command("deepseek", str(shim), "中文\n继续", {}, CliParamsConfig(), session_id="session-existing")
    run = subprocess.run(cmd, input="中文\n继续".encode("utf-8"), capture_output=True, timeout=15)
    result = json.loads(run.stdout)
    assert run.returncode == 0 and stdin is True
    assert result["args"] == ["--profile", "headless", "--json", "--session-id", "session-existing", "-"]
    assert result["input"] == "中文\n继续"
    assert result["patch"] is None


@pytest.mark.parametrize("selection,expected", [
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
    result = json.loads(run.stdout)
    assert result["patch"][0]["config"] == {**inherited, **expected}
    assert result["args"][:4] == ["--profile", "headless", "--patch", str(user_patch)]
    assert result["args"][-4:] == ["--patch", result["patchPath"], "--json", "-"]
    assert not Path(result["patchPath"]).parent.exists()
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

