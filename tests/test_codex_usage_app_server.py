import json
import io

from bot.codex_usage.app_server_rate_limits import resolve_account_rate_limit


def test_resolve_account_rate_limit_selects_codex_bucket(monkeypatch) -> None:
    stdout = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "rateLimits": {
                            "limitId": "codex_bengalfox",
                            "primary": {"usedPercent": 99},
                        },
                        "rateLimitsByLimitId": {
                            "codex": {
                                "limitId": "codex",
                                "planType": "pro",
                                "primary": {
                                    "usedPercent": 17,
                                    "windowDurationMins": 10_080,
                                    "resetsAt": 1_787_011_285,
                                },
                            },
                        },
                    },
                }
            ),
        ]
    )
    class FakeStdin(io.StringIO):
        def close(self) -> None:
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = FakeStdin()
            self.stdout = io.StringIO(stdout)
            self.returncode = 0
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout=None) -> int:
            return self.returncode

        def kill(self) -> None:
            self.terminated = True

    calls: list[dict[str, object]] = []
    process = FakeProcess()

    def fake_popen(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return process

    monkeypatch.setattr(
        "bot.codex_usage.app_server_rate_limits.subprocess.Popen",
        fake_popen,
    )

    sample = resolve_account_rate_limit(
        executable="codex",
        env={"CODEX_HOME": "C:\\temp\\codex"},
        limit_id="codex",
    )

    assert sample is not None
    assert sample.used_percent == 17
    assert sample.window_minutes == 10_080
    assert sample.plan_type == "pro"
    request_text = process.stdin.getvalue()
    assert '"method":"account/rateLimits/read"' in request_text
    assert '"params":null' in request_text
    assert calls[0]["args"][0] == ["codex", "app-server", "--stdio"]


def test_resolve_account_rate_limit_returns_none_for_missing_codex_bucket(monkeypatch) -> None:
    stdout = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"rateLimitsByLimitId": {"codex_bengalfox": {}}},
        }
    )

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(stdout)
            self.returncode = 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout=None) -> int:
            return self.returncode

        def kill(self) -> None:
            pass

    monkeypatch.setattr(
        "bot.codex_usage.app_server_rate_limits.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    assert (
        resolve_account_rate_limit(
            executable="codex",
            env=None,
            limit_id="codex",
        )
        is None
    )
