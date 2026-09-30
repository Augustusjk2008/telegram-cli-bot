import asyncio
import os
import sys

import pytest

from bot.codex_server.client import CodexServerClient, CodexServerError, noninteractive_response


FAKE_SERVER = r'''
import json, sys, time, subprocess
def emit(x):
 print(json.dumps(x), flush=True)
held = None
for line in sys.stdin:
 p = json.loads(line)
 method = p.get('method')
 if method == 'initialize':
  emit({'id': p['id'], 'result': {'userAgent': 'codex/0.159.2'}})
 elif method == 'initialized':
  pass
 elif method == 'hold':
  held = p
 elif method == 'release':
  emit({'method':'notice','params':{'value':1}})
  emit({'id':p['id'],'result':{'value':'second'}})
  emit({'id':held['id'],'result':{'value':'first'}})
 elif method == 'approvals':
  held = p
  emit({'id':'server-approval','method':p['params']['method'],'params':{}})
 elif p.get('id') == 'server-approval':
  emit({'id':held['id'],'result':p})
 elif method == 'malformed':
  print('this is not json',flush=True)
 elif method == 'oversized':
  print('x'*2048,flush=True)
 elif method == 'flood':
  for i in range(400): emit({'method':'notice','params':{'i':i}})
 elif method == 'exit':
  sys.stderr.write('isolated child failed\n'); sys.stderr.flush()
  sys.exit(7)
 elif method == 'child':
  child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
  emit({'id':p['id'],'result':{'pid':child.pid}})
 elif method == 'never':
  pass
 else:
  emit({'id':p['id'],'result':{}})
'''


async def start_fake(tmp_path, **env):
    path = tmp_path / "fake_server.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return await CodexServerClient.start([sys.executable, "-u", str(path)], cwd=str(tmp_path),
                                         env={**os.environ, **env}, timeout=1)


@pytest.mark.asyncio
async def test_matching_interleaving_and_single_reader(tmp_path):
    client = await start_fake(tmp_path)
    try:
        first = asyncio.create_task(client.request("hold", {}))
        await asyncio.sleep(.03)
        second = await client.request("release", {})
        assert second == {"value": "second"}
        assert await first == {"value": "first"}
        events = client.events()
        assert (await anext(events))["method"] == "notice"
        with pytest.raises(CodexServerError, match="一个 reader"):
            await anext(client.events())
        await events.aclose()
    finally:
        await client.close()
    assert client.process.poll() is not None
    assert all(not thread.is_alive() for thread in client._threads)


@pytest.mark.asyncio
async def test_incompatible_server_version_is_rejected(tmp_path):
    path = tmp_path / "bad_version_server.py"
    path.write_text(FAKE_SERVER.replace("codex/0.159.2", "codex/0.159.1"), encoding="utf-8")
    with pytest.raises(CodexServerError, match="不兼容"):
        await CodexServerClient.start(
            [sys.executable, "-u", str(path)],
            cwd=str(tmp_path),
            env={**os.environ},
            timeout=1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("method, expected", [
    ("item/commandExecution/requestApproval", {"decision": "decline"}),
    ("item/fileChange/requestApproval", {"decision": "decline"}),
    ("item/permissions/requestApproval", {"permissions": {}, "scope": "turn"}),
    ("item/tool/requestUserInput", {"answers": {}}),
    ("mcpServer/elicitation/request", {"action": "decline"}),
    ("execCommandApproval", {"decision": {"denied": {"rejection": "Non-interactive client cannot approve this request"}}}),
    ("applyPatchApproval", {"decision": {"denied": {"rejection": "Non-interactive client cannot approve this request"}}}),
])
async def test_server_requests_receive_noninteractive_responses(tmp_path, method, expected):
    client = await start_fake(tmp_path)
    try:
        reply = await client.request("approvals", {"method": method})
        assert reply == {"id": "server-approval", "result": expected}
    finally:
        await client.close()


def test_unknown_request_explicitly_rejected():
    assert noninteractive_response("unknown")["error"]["code"] == -32601


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["never", "malformed", "oversized", "exit", "flood"])
async def test_failure_timeout_and_bounded_buffers_close_only_owned_child(tmp_path, method):
    client = await start_fake(tmp_path, TCB_CLI_MAX_LINE_BYTES="1024")
    with pytest.raises(CodexServerError):
        await client.request(method, {}, timeout=.3)
    await client.close()
    assert client.process.poll() is not None
    assert len(client._stderr) <= client.limits.raw_tail_max_bytes
    assert client._events.qsize() <= 256
    assert client._packets.qsize() <= client.limits.queue_max_chunks


@pytest.mark.asyncio
async def test_request_cancel_closes_unknown_outcome(tmp_path):
    client = await start_fake(tmp_path)
    task = asyncio.create_task(client.request("never", {}))
    await asyncio.sleep(.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client.alive
    assert client.process.poll() is not None


def test_windows_selector_compatible(tmp_path):
    async def scenario():
        client = await start_fake(tmp_path)
        try:
            assert await client.request("ping", {}) == {}
        finally:
            await client.close()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(scenario())


@pytest.mark.asyncio
async def test_owned_descendant_is_closed_even_after_parent_exit(tmp_path):
    import psutil
    client = await start_fake(tmp_path)
    try:
        child = psutil.Process((await client.request("child", {}))["pid"])
        with pytest.raises(CodexServerError):
            await client.request("exit", {})
    finally:
        await client.close()
    await asyncio.to_thread(child.wait, 3)
    assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
