import json
from pathlib import Path
import shutil
import subprocess

import pytest

from bot.cli import DeepSeekJsonStreamParser, build_cli_command
from bot.cli_params import CliParamsConfig
from bot.deepseek_cli import _resolve_desktop_dsh_runtime, build_deepseek_invocation


def deepseek_parser(*events, limit=4096):
    parser = DeepSeekJsonStreamParser(raw_tail_max_bytes=4096, final_text_max_bytes=limit)
    for event in events:
        parser.consume_line(json.dumps(event, ensure_ascii=False) + "\n")
    return parser


SESSION = {"type": "session", "sessionId": "session-test", "cwd": "C:\\workspace"}
COMPLETED = {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}}


@pytest.fixture
def desktop_dsh(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Desktop launcher regression")
    root = tmp_path / "DeepSeek Harness 中文 #path"
    app = root / "resources" / "app.asar" / "dsh"
    packages = app / "node_modules" / "@deepseek-ai"
    dsh_package = packages / "dsh"
    (dsh_package / "lib").mkdir(parents=True)
    (dsh_package / "package.json").write_text(json.dumps({"name": "@deepseek-ai/dsh", "type": "module"}), encoding="utf-8")
    (dsh_package / "lib" / "bin.js").write_text('''
import { readFileSync } from "node:fs";
export async function runCli() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const args = process.argv.slice(2);
  const patchPaths = args.flatMap((arg, index) => arg === "--patch" ? [args[index + 1]] : []);
  const patchPath = patchPaths.at(-1) || null;
  console.log(JSON.stringify({ args, input, patchPath,
    patch: patchPath ? JSON.parse(readFileSync(patchPath, "utf8")) : null,
    patches: patchPaths.map((path) => ({ path, entries: JSON.parse(readFileSync(path, "utf8")) })) }));
}
''', encoding="utf-8")
    (packages / "dsh-desktop-host" / "lib").mkdir(parents=True)
    (packages / "dsh-desktop-host" / "package.json").write_text(json.dumps({"type": "module"}), encoding="utf-8")
    (packages / "dsh-desktop-host" / "lib" / "cli.js").write_text('''
import { runCli } from "@deepseek-ai/dsh/lib/bin.js";
export async function runDesktopCli() { await runCli(); }
''', encoding="utf-8")
    (packages / "dsh-app-boot" / "lib").mkdir(parents=True)
    (packages / "dsh-app-boot" / "package.json").write_text(json.dumps({"type": "module", "exports": "./lib/index.js"}), encoding="utf-8")
    (packages / "dsh-app-boot" / "lib" / "index.js").write_text('''
import { readFileSync } from "node:fs";
export function loadProfile(_, name) { return { dir: name, patchPath: `${name}.json`, patches: [] }; }
export function loadOverlayPatches(_, file) { return JSON.parse(readFileSync(file, "utf8")); }
export function readProfilePatches(_, context, profile) {
  if (profile?.dir === "desktop" && process.env.TCB_TEST_DESKTOP_PROVIDER === "1") {
    return [
      { id: "agent-default-model", name: "@deepseek-ai/dsh-agent-default-model", config: {
        provider: "opencode-go", model: "deepseek-v4.1-flash", reasoningEffort: "max",
      } },
      { id: "credentials", name: "@deepseek-ai/dsh-credentials-local", disabled: false },
      { id: "llm-pi-ai", name: "@deepseek-ai/dsh-llm-pi-ai", config: {
        providers: { "opencode-go": { apiKeyEnv: "OPENCODE_GO_API_KEY" } },
      } },
      { id: "llm-deepseek", name: "@deepseek-ai/dsh-llm-deepseek-api-key", disabled: true },
    ];
  }
  return context.overlays;
}
export function composeEntries([patches]) {
  const entries = [];
  const indexes = new Map();
  for (const entry of patches.flat()) {
    if (!entry?.id) { entries.push(entry); continue; }
    const previous = indexes.get(entry.id);
    if (previous === undefined) indexes.set(entry.id, entries.length), entries.push(entry);
    else entries[previous] = entry;
  }
  return entries;
}
''', encoding="utf-8")
    (packages / "dsh-home-paths" / "lib").mkdir(parents=True)
    (packages / "dsh-home-paths" / "package.json").write_text(json.dumps({"type": "module", "exports": "./lib/index.js"}), encoding="utf-8")
    (packages / "dsh-home-paths" / "lib" / "index.js").write_text('export function resolveDshHome() { return "test-home"; }\n', encoding="utf-8")
    node_exe = Path(node).resolve()
    wrapper = root / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "@echo off\n"
        f'"{node_exe}" --expose-internals "%~dp0..\\..\\..\\app.asar\\dsh\\node_modules\\@deepseek-ai\\dsh-desktop-host\\lib\\cli.js" %*\n',
        encoding="utf-8",
    )
    return wrapper, dsh_package


@pytest.mark.parametrize("prompt", ["中文输入\n第二行", "/help", "//继续"])
def test_deepseek_uses_stdin_and_only_returned_session_ids(desktop_dsh, prompt):
    wrapper, _ = desktop_dsh
    config = CliParamsConfig.from_dict({"deepseek": {"extra_args": ["--patch", "C:\\配置 文件\\model.yml"]}})
    for session_id in (None, "session-returned"):
        command, stdin = build_cli_command("deepseek", str(wrapper), prompt, {}, config, session_id=session_id)
        assert command[2].endswith("deepseek_launch.mjs")
        assert command[4] == command[0]
        if session_id:
            assert command[-4:] == ["--json", "--session-id", session_id, "-"]
        else:
            assert command[-2:] == ["--json", "-"]
        assert stdin is True and prompt not in command


def test_deepseek_desktop_wrapper_resolves_electron_host_and_bundled_package(desktop_dsh):
    wrapper, _ = desktop_dsh
    runtime = _resolve_desktop_dsh_runtime(wrapper, wrapper.read_text(encoding="utf-8"))
    assert runtime is not None
    assert runtime.electron == Path(shutil.which("node")).resolve()
    assert runtime.host_entry.as_posix().endswith("app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js")
    assert runtime.dsh_entry.as_posix().endswith("app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js")


@pytest.mark.parametrize("permission_mode", ["workspace-write", "danger-full-access"])
def test_deepseek_permission_mode_and_electron_mode_are_child_env(desktop_dsh, permission_mode):
    wrapper, _ = desktop_dsh
    env = {}
    command, stdin = build_cli_command("deepseek", str(wrapper), "hello", env, CliParamsConfig.from_dict({"deepseek": {"permission_mode": permission_mode}}))
    assert command[0].lower().endswith(".exe") and command[1] == "--expose-internals"
    assert command[-2:] == ["--json", "-"] and stdin is True
    assert env == {"DSH_PERMISSION_MODE": permission_mode, "ELECTRON_RUN_AS_NODE": "1"}


def test_deepseek_desktop_wrapper_runs_once_and_preserves_stdin_and_session(desktop_dsh):
    wrapper, _ = desktop_dsh
    cmd, stdin = build_cli_command("deepseek", str(wrapper), "中文\n继续", {}, CliParamsConfig(), session_id="session-existing")
    run = subprocess.run(cmd, input="中文\n继续".encode("utf-8"), capture_output=True, timeout=15)
    result = json.loads(run.stdout.decode("utf-8"))
    assert run.returncode == 0 and stdin is True
    assert result["args"] == ["--profile", "headless", "--json", "--session-id", "session-existing", "-"]
    assert result["input"] == "中文\n继续"


def test_deepseek_rejects_npm_shim_and_gui_path(tmp_path):
    npm = tmp_path / "npm" / "dsh.cmd"
    npm.parent.mkdir()
    npm.write_text('@node "%~dp0/node_modules/@deepseek-ai/dsh/lib/bin.js" %*', encoding="utf-8")
    with pytest.raises(ValueError, match="必须使用桌面版 dsh.cmd.*npm CLI"):
        build_deepseek_invocation(str(npm), {})
    gui = tmp_path / "DeepSeek Harness.exe"
    gui.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="不要填写 DeepSeek Harness.exe"):
        build_deepseek_invocation(str(gui), {})


@pytest.mark.parametrize("selection,expected", [
    ({"model": "deepseek-v4-pro"}, {"model": "deepseek-v4-pro", "reasoningEffort": "low"}),
    ({"reasoning_effort": "off"}, {"model": "custom-model", "reasoningEffort": "off"}),
    ({"model": "deepseek-flash", "reasoning_effort": "max"}, {"model": "deepseek-flash", "reasoningEffort": "max"}),
])
def test_deepseek_selection_overlays_preserve_provider_and_cleanup(desktop_dsh, tmp_path, selection, expected):
    wrapper, _ = desktop_dsh
    inherited = {"provider": "deepseek-account", "model": "custom-model", "reasoningEffort": "low"}
    user_patch = tmp_path / "user model.json"
    user_patch.write_text(json.dumps([{"id": "agent-default-model", "name": "@deepseek-ai/dsh-agent-default-model", "config": inherited}]), encoding="utf-8")
    original = user_patch.read_bytes()
    params = CliParamsConfig.from_dict({"deepseek": {**selection, "extra_args": ["--patch", str(user_patch)]}})
    cmd, _ = build_cli_command("deepseek", str(wrapper), "hello", {}, params)
    run = subprocess.run(cmd, input="hello", capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert run.returncode == 0, run.stderr
    metadata, result = [json.loads(line) for line in run.stdout.splitlines()]
    assert metadata == {"type": "orbit_model", "model": expected["model"]}
    assert result["patch"][0]["config"] == {**inherited, **expected}
    assert result["args"][:4] == ["--profile", "headless", "--patch", str(user_patch)]
    assert result["args"][-4:-2] == ["--patch", result["patchPath"]]
    assert not Path(result["patchPath"]).parent.exists()
    assert user_patch.read_bytes() == original


def test_deepseek_inherited_model_emits_orbit_metadata_without_dynamic_patch(desktop_dsh, tmp_path):
    wrapper, _ = desktop_dsh
    inherited = {"provider": "deepseek-account", "model": "custom-model", "reasoningEffort": "low"}
    user_patch = tmp_path / "inherited model.json"
    user_patch.write_text(json.dumps([{"id": "agent-default-model", "name": "@deepseek-ai/dsh-agent-default-model", "config": inherited}]), encoding="utf-8")
    params = CliParamsConfig.from_dict({"deepseek": {"extra_args": ["--patch", str(user_patch)]}})
    cmd, _ = build_cli_command("deepseek", str(wrapper), "hello", {}, params)
    run = subprocess.run(cmd, input=b"hello", capture_output=True, timeout=15)
    lines = run.stdout.decode("utf-8").splitlines()
    metadata, result = [json.loads(line) for line in lines]
    assert metadata == {"type": "orbit_model", "model": "custom-model"}
    assert result["patchPath"] == str(user_patch)


def test_deepseek_bridges_desktop_provider_into_headless(desktop_dsh, monkeypatch):
    wrapper, _ = desktop_dsh
    monkeypatch.setenv("TCB_TEST_DESKTOP_PROVIDER", "1")
    params = CliParamsConfig.from_dict({"deepseek": {"model": "deepseek-v4.1-flash", "reasoning_effort": "max"}})
    cmd, _ = build_cli_command("deepseek", str(wrapper), "hello", {}, params)
    run = subprocess.run(cmd, input="hello", capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert run.returncode == 0, run.stderr
    metadata, result = [json.loads(line) for line in run.stdout.splitlines()]
    assert metadata == {"type": "orbit_model", "model": "deepseek-v4.1-flash"}
    assert result["patch"][0]["config"] == {
        "provider": "opencode-go",
        "model": "deepseek-v4.1-flash",
        "reasoningEffort": "max",
    }
    args = result["args"]
    bridge = result["patches"][0]["entries"]
    assert {row["id"] for row in bridge} == {"credentials", "agent-default-model", "llm-pi-ai", "llm-deepseek"}
    assert next(row for row in bridge if row["id"] == "credentials")["disabled"] is False
    assert next(row for row in bridge if row["id"] == "llm-pi-ai")["config"]["providers"]["opencode-go"]["apiKeyEnv"] == "OPENCODE_GO_API_KEY"
    assert next(row for row in bridge if row["id"] == "llm-deepseek")["disabled"] is True
    assert not Path(result["patches"][0]["path"]).parent.exists()


def test_deepseek_bridges_desktop_default_without_selection(desktop_dsh, monkeypatch):
    wrapper, _ = desktop_dsh
    monkeypatch.setenv("TCB_TEST_DESKTOP_PROVIDER", "1")
    cmd, _ = build_cli_command("deepseek", str(wrapper), "hello", {}, CliParamsConfig())
    run = subprocess.run(cmd, input="hello", capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert run.returncode == 0, run.stderr
    metadata, result = [json.loads(line) for line in run.stdout.splitlines()]
    assert metadata == {"type": "orbit_model", "model": "deepseek-v4.1-flash"}
    assert result["patch"][0]["id"] == "agent-default-model"
    assert result["patch"][0]["config"]["provider"] == "opencode-go"
    assert len(result["patches"]) == 1


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

