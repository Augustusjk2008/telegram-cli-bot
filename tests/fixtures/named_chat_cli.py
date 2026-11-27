"""Local CLI stand-ins for named chat execution tests. The launcher supplies its identity."""

import json
import os
from pathlib import Path
import sys
import time


def emit(**event):
    print(json.dumps(event), flush=True)


def main():
    cli, *args = sys.argv[1:]
    if cli == "antigravity":
        prompt = args[args.index("-p") + 1]
    else:
        prompt = sys.stdin.read().split("\n\nHost completion protocol:", 1)[0].strip()
    assert prompt and all(c.isalnum() or c in "- " for c in prompt), repr(prompt)
    record = {"cli": cli, "args": args}
    if cli == "antigravity":
        record["telemetry"] = os.environ["TCB_ANTIGRAVITY_STATUSLINE_PATH"]
    Path(f"{prompt}.json").write_text(json.dumps(record), encoding="utf-8")
    if prompt.startswith("hold-"):
        Path(f"{prompt}.started").touch()
        deadline = time.monotonic() + 20
        while not Path(f"{prompt}.finish").exists():
            assert time.monotonic() < deadline, prompt
            time.sleep(0.02)

    if cli == "codex":
        assert args[0] == "exec" and "--json" in args
        thread = args[args.index("resume") + 1] if "resume" in args else f"native-{prompt}"
        emit(type="thread.started", thread_id=thread)
        emit(type="item.completed", item={"type": "assistant_message", "text": prompt})
        emit(type="turn.completed")
    elif cli == "claude":
        assert args[0] == "-p" and args[args.index("--output-format") + 1] == "stream-json"
        flag = "-r" if "-r" in args else "--session-id"
        thread = args[args.index(flag) + 1]
        emit(type="system", subtype="init", session_id=thread)
        emit(type="result", subtype="success", result=prompt, session_id=thread,
             model_usage_since_last_result={"test-claude": {"costUSD": 0.25}})
    elif cli == "antigravity":
        native = f"agy-{prompt}"
        remaining = int(prompt.split("-")[-1])
        payload = {"conversation_id": native, "context_window": {
            "context_window_size": 1000, "remaining_percentage": remaining,
            "used_percentage": 100 - remaining,
        }}
        path = Path(record["telemetry"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        emit(event="init", conversation_id=native, init={})
        emit(event="result", result={"conversation_id": native, "status": "SUCCESS", "response": prompt})
    else:
        raise AssertionError(cli)


if __name__ == "__main__":
    main()
