# Code Review: Bugs, Redundancy, and UX Improvements

---

## 1. Bugs

### B1 — [CRITICAL] Blocking event loop in `_terminate_process_tree` (`handlers/chat.py:59`)
Declared `async def` but contains purely synchronous blocking calls:
- `process.wait(timeout=3)` — blocks up to 3 s
- `subprocess.run(["taskkill", ...], timeout=5)` — blocks up to 5 s
- `process.kill()` + `process.wait(timeout=2)` — blocks up to 2 more s

Total potential block: **~10 s** on the asyncio event loop, freezing ALL bots during that window.

**Fix:** Extract sync logic to a plain function; wrap with `loop.run_in_executor(None, ...)` inside the async version.

---

### B2 — [CRITICAL] Session store read-modify-write is not atomic (`session_store.py:89`)
`save_session()` calls `load_session_ids()` (acquires+releases `_store_lock`), then `save_session_ids(data)` (acquires+releases `_store_lock`) as two separate lock acquisitions. Between the two calls, another thread can write the file, causing silent data loss. Same issue in `remove_session` and `remove_all_sessions_for_bot`.

**Fix:** Hold `_store_lock` across the entire read-modify-write in each function.

---

### B3 — [HIGH] `threading.Lock` acquired synchronously in async handlers (`handlers/chat.py:613, 754`)
`with session._lock:` is called directly inside coroutines (`handle_text_message`, `handle_stop_callback`). `session._lock` is a `threading.Lock`, not an `asyncio.Lock`. If another thread holds the lock, this blocks the asyncio event loop thread.

**Analysis after tracing all usages:** The lock is *never held across an `await`* in any handler — it's always acquired, sync work done, released, then `await` happens. The only possible contention is `terminate_process()` (holds lock up to 5s) called from `cleanup_expired_sessions`. However, `cleanup_expired_sessions` only touches sessions that have been idle for `SESSION_TIMEOUT` seconds — by definition not the same session an active user is messaging. In practice, the risk is negligible.

**Status:** Won't fix without a larger refactor (switching to `asyncio.Lock` would require making `terminate_process` async, which ripples through sync call sites).

---

### B4 — [HIGH] `import select` and `import os` inside inner function (`handlers/chat.py:131`)
`select` and `os` are imported inside `read_stdout()` which is called in a tight loop of a background thread. The `os` module is already imported at the top of the file. The `select` import is also redundant per call. Minor performance cost, but also a code smell.

**Fix:** Move both imports to the top of the file.

---

### B5 — [MEDIUM] `get_profile` silently falls back to `main_profile` for unknown aliases (`manager.py:299`)
```python
def get_profile(self, alias: str) -> BotProfile:
    if alias == self.main_profile.alias:
        return self.main_profile
    return self.managed_profiles.get(alias, self.main_profile)  # silent fallback!
```
Any caller passing a typo or stale alias silently gets the main profile instead of an error, which can cause commands to be applied to the wrong bot.

**Fix:** Return `None` or raise `KeyError` for unknown aliases; update callers to handle the miss explicitly.

---

### B6 — [MEDIUM] Dead backward-compatibility code path always skipped (`cli.py:133`)
In `build_cli_command`, `handle_text_message` always passes `profile.cli_params`, so the `if params_config is not None:` branch is always taken from that path. However, `api_service.py` and `test_cli.py` call `build_cli_command` without `params_config`, so the fallback is still reachable. The fallback block is a maintenance burden — it duplicates all three CLI command builders.

**Fix:** Update `api_service.py` to pass a `CliParamsConfig`, update `test_cli.py`, then remove the fallback block.

---

### B7 — [MEDIUM] Kimi session resumption has no error-reset path (`handlers/chat.py:627`)
For Claude and Codex there is logic to detect session initialization failure and reset `session_id`. For Kimi, `cli_session_id = session.kimi_session_id` is passed unconditionally once set, with no corresponding "should_reset_kimi_session" check. A stale Kimi session ID will keep being reused silently after it expires.

---

### B8 — [LOW] `asyncio.get_event_loop()` in sync polling-error callback (`manager.py:85`)
`_make_polling_error_callback` returns a sync callback that calls `asyncio.get_event_loop().time()`. In Python ≥ 3.10, `get_event_loop()` emits a `DeprecationWarning` when there is no current event loop in the calling thread. Should use `time.monotonic()` or pass the loop reference at closure creation.

---

## 2. Redundant Code

### R1 — `get_profile` vs `_get_profile_for_update` (`manager.py:298–309`)
Two nearly identical methods differing only in whether they raise on unknown alias. The silent fallback in `get_profile` is confusing and error-prone (see B5). Unify to one method with a `strict=False` flag, or simply always raise.

---

### R2 — `_get_store_path()` is a no-op indirection (`session_store.py:23`)
```python
def _get_store_path() -> Path:
    return STORE_FILE
```
This function adds zero value — it just returns the module-level constant. Every call site can use `STORE_FILE` directly.

---

### R3 — Duplicate progress-message delete + chunk-send pattern (`handlers/chat.py:468–540`)
`collect_cli_output` and `stream_codex_json_output` both contain nearly identical blocks:
- delete progress message
- chunk output into 900-char pieces
- send each chunk with `reply_text`
- (on timeout) send two extra follow-up messages

This 40-line pattern is duplicated verbatim. Extract to a shared `_send_cli_result(update, progress_message, final_text, icon, timed_out, ...)` helper.

---

### R4 — `import os` and `import select` inside `read_stdout()` inner function (`handlers/chat.py:131, 335`)
Both `collect_cli_output` and `stream_codex_json_output` import `os` (and `select` on Unix) inside the inner `read_stdout()` function. `os` is already imported at module top level. These should be removed from the inner function.

---

### R5 — `threading.Event().wait(0.1)` creates a throw-away Event object (`handlers/chat.py:346`)
```python
threading.Event().wait(0.1)  # busy-wait workaround
```
This constructs a new Event object just to call `.wait()` on it once. Use `time.sleep(0.1)` instead.

---

### R6 — `save_session_ids` / `load_session_ids` are bypassed after B2 fix
After fixing B2, the public `load_session_ids` / `save_session_ids` functions are no longer called by any of the mutating helpers. They are still used by `load_session` (read-only). Consider whether the write-side helpers should be made private or removed.

---

## 3. UX Improvement Opportunities

### U1 — No feedback when a message is ignored because bot is busy
If a user sends a message while the bot is processing (`session.is_processing == True`), `handle_text_message` silently returns without any reply. The user has no idea whether their message was received. A short "⏳ 正在处理上一条消息，请稍候..." reply would prevent confusion and repeated sends.

---

### U2 — Timeout messages split across 3+ separate sends
On timeout, up to N chunk messages are sent, then a timeout notice, then a session-retention notice — potentially 4+ separate Telegram messages in quick succession. Consolidate the timeout notice and session-retention hint into the last chunk message (or a single follow-up) to reduce notification noise.

---

### U3 — No progress indication for `collect_cli_output` (non-Codex CLIs)
`stream_codex_json_output` shows real-time partial output previews during processing. `collect_cli_output` (used by Kimi and Claude) only shows elapsed time with no content preview. Adding a truncated preview of the last N chars of stdout would give users confidence the CLI is working.

---

### U4 — `/cd` command accepts any string without validating directory existence
Users can `/cd` to a non-existent path. The session's `working_dir` is updated, but the next CLI call will immediately fail with a confusing error. The handler should check `os.path.isdir(path)` and reject invalid paths immediately with a clear message.

---

### U5 — Bot-busy state has no stop button
When the user sends a new message while the bot is busy (U1), there is no way to cancel the in-progress task from the new message context. The "busy" reply itself could include a "🛑 停止任务" inline button (reusing the same `stop_task` callback) so users can immediately interrupt without scrolling back.

---

### U6 — No session ID display in `/status`
The `/status` or session-info commands don't surface active session IDs (codex/kimi/claude). Power users debugging continuity issues have no way to know which session is in use without reading the log file.

---

## Summary Table

| ID | Severity | File | Status |
|----|----------|------|--------|
| B1 | CRITICAL | `handlers/chat.py:59` | **FIXED** |
| B2 | CRITICAL | `session_store.py:89` | **FIXED** |
| B3 | HIGH | `handlers/chat.py:613,754` | Won't fix (risk negligible in practice) |
| B4 | HIGH | `sessions.py:20–31` | **FIXED** |
| B5 | MEDIUM | `manager.py:298` | **FIXED** |
| B6 | MEDIUM | `cli.py:133` | **FIXED** |
| B7 | MEDIUM | `sessions.py` | **FIXED** |
| B8 | LOW | `manager.py:85` | **FIXED** |
| R1 | Medium | `manager.py:298–309` | Won't fix (different error types needed) |
| R2 | Low | `session_store.py:23` | **FIXED** |
| R3 | Medium | `handlers/chat.py:468–540` | Open |
| R4 | Low | `handlers/chat.py:131,335` | **FIXED** |
| R5 | Low | `handlers/chat.py:346` | **FIXED** |
| R6 | Low | `session_store.py` | Won't fix (used by tests) |
| U1 | High | `handlers/chat.py` | **FIXED** |
| U2 | Medium | `handlers/chat.py` | **FIXED** |
| U3 | Medium | `handlers/chat.py` | **FIXED** |
| U4 | Medium | `handlers/basic.py` | N/A (already handled) |
| U5 | Low | `handlers/chat.py` | **FIXED** |
| U6 | Low | `handlers/basic.py` | N/A (`/start` already shows session IDs) |
