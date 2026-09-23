from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
import hashlib
import io
import posixpath
import stat
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import paramiko
import pytest

from bot.remote_workspace import transport as remote


ROOT = "/home/dev/project"
KEY = Mock(asbytes=Mock(return_value=b"server-public-key"), get_name=Mock(return_value="ssh-ed25519"))
FINGERPRINT = remote._fingerprint(KEY)


def attrs(node, filename=None):
    return SimpleNamespace(st_mode=node["mode"], st_size=len(node.get("data", b"")),
                           st_mtime=node.get("mtime", 100), filename=filename)


class MemoryFile(io.BytesIO):
    def __init__(self, node, reads):
        self.node = node
        self.reads = reads
        super().__init__(node.get("data", b""))

    def read(self, size=-1):
        result = super().read(size)
        self.reads.append((size, len(result)))
        return result

    def write(self, value):
        result = super().write(value)
        self.node["data"] = self.getvalue()
        return result

    def stat(self):
        return attrs(self.node)

    def chmod(self, mode):
        self.node["mode"] = stat.S_IFREG | mode

    def utime(self, times):
        raise AssertionError("Transport must not synthesize remote mtimes")


class MemorySFTP:
    def __init__(self, nodes):
        self.nodes = nodes
        self.channel = Mock(closed=False)
        self.closed = False
        self.rename_calls = 0
        self.fail_after_rename = False
        self.atomic_supported = True
        self.stat_paths = []
        self.reads = []

    def get_channel(self):
        return self.channel

    def close(self):
        self.closed = self.channel.closed = True

    def normalize(self, path):
        if not path.startswith("/"):
            path = "/home/dev/" + path
        pending, parts = path.split("/"), []
        followed = 0
        while pending:
            part = pending.pop(0)
            if part in {"", "."}:
                continue
            if part == "..":
                parts = parts[:-1]
                continue
            parts.append(part)
            current = "/" + "/".join(parts)
            node = self.nodes.get(current)
            if node and "link" in node:
                followed += 1
                if followed > 40:
                    raise OSError(errno.ELOOP, "Symlink loop")
                parts.pop()
                if node["link"].startswith("/"):
                    parts = []
                pending = node["link"].split("/") + pending
        return "/" + "/".join(parts)

    def stat(self, path):
        self.stat_paths.append(path)
        node = self.nodes.get(self.normalize(path))
        if node is None:
            raise FileNotFoundError(errno.ENOENT, "Missing")
        return attrs(node)

    def lstat(self, path):
        path = posixpath.join(self.normalize(posixpath.dirname(path)), posixpath.basename(path))
        if posixpath.basename(path) in {".", "..", ""}:
            path = self.normalize(path)
        if path not in self.nodes:
            raise FileNotFoundError(errno.ENOENT, "Missing")
        return attrs(self.nodes[path])

    def listdir_iter(self, path, read_aheads=1):
        for name, node in list(self.nodes.items()):
            if name != path and posixpath.dirname(name) == path:
                yield attrs(node, posixpath.basename(name))

    def open(self, path, mode):
        path = self.normalize(path)
        if "x" in mode:
            if path in self.nodes:
                raise FileExistsError(errno.EEXIST, "Exists")
            self.nodes[path] = {"mode": stat.S_IFREG | 0o600, "data": b"", "mtime": 100}
        if path not in self.nodes:
            raise FileNotFoundError(errno.ENOENT, "Missing")
        return MemoryFile(self.nodes[path], self.reads)

    def rename(self, old, new):
        if new in self.nodes:
            raise FileExistsError(errno.EEXIST, "Exists")
        self._rename(old, new)

    def posix_rename(self, old, new):
        if not self.atomic_supported:
            raise OSError("Operation unsupported")
        self._rename(old, new)

    def _rename(self, old, new):
        self.rename_calls += 1
        self.nodes[new] = self.nodes.pop(old)
        if self.fail_after_rename:
            raise EOFError("Response lost after mutation")

    def remove(self, path):
        if path not in self.nodes:
            raise FileNotFoundError(errno.ENOENT, "Missing")
        del self.nodes[path]

    def mkdir(self, path):
        if path in self.nodes:
            raise FileExistsError(errno.EEXIST, "Exists")
        self.nodes[path] = {"mode": stat.S_IFDIR | 0o755}


class Channel:
    def __init__(self, *, stdout=b"", stderr=b"", running=False):
        self.closed = False
        self.stdout, self.stderr = bytearray(stdout), bytearray(stderr)
        self.running = running
        self.commands = []
        self.sent = b""
        self.size = None
        self.started = threading.Event()

    def settimeout(self, timeout):
        self.timeout = timeout

    def exec_command(self, command):
        self.commands.append(command)
        self.started.set()

    def shutdown_write(self):
        pass

    def recv_ready(self):
        return bool(self.stdout)

    def recv_stderr_ready(self):
        return bool(self.stderr)

    def recv(self, count):
        result = bytes(self.stdout[:count])
        del self.stdout[:count]
        return result

    def recv_stderr(self, count):
        result = bytes(self.stderr[:count])
        del self.stderr[:count]
        return result

    def exit_status_ready(self):
        return self.closed or not self.running

    def recv_exit_status(self):
        return -1 if self.closed else 0

    def get_pty(self, **kwargs):
        self.size = kwargs

    def resize_pty(self, **kwargs):
        self.size = kwargs

    def sendall(self, data):
        self.sent += data

    def close(self):
        self.closed = True


@pytest.fixture
def ssh(monkeypatch):
    nodes = {p: {"mode": stat.S_IFDIR | 0o755} for p in ("/", "/home", "/home/dev", ROOT, "/outside", "/outside/deep")}
    nodes[ROOT + "/file.txt"] = {"mode": stat.S_IFREG | 0o640, "data": b"one\ntwo\n", "mtime": 100}
    nodes["/outside/secret"] = {"mode": stat.S_IFREG | 0o600, "data": b"secret", "mtime": 100}
    state = SimpleNamespace(nodes=nodes, clients=[], known=False, auth_error=None, next_channel=None, on_connect=None)

    class Client:
        def __init__(self):
            self.closed = False
            self.loaded = False
            self.auth_attempts = 0
            self.sftp = MemorySFTP(nodes)
            self.open_sftp = Mock(return_value=self.sftp)
            self.transport = Mock()
            self.transport.is_active.return_value = True
            self.transport.is_authenticated.return_value = True
            self.transport.get_remote_server_key.return_value = KEY
            self.transport.open_session.side_effect = lambda **kwargs: state.next_channel or Channel(running=True)
            state.clients.append(self)

        def load_system_host_keys(self, *args):
            self.loaded = True

        def set_missing_host_key_policy(self, policy):
            self.policy = policy

        def connect(self, **kwargs):
            self.kwargs = kwargs
            if not (self.loaded and state.known):
                self.policy.missing_host_key(self, kwargs["hostname"], KEY)
            self.auth_attempts += 1
            if state.on_connect:
                state.on_connect(kwargs)
            if state.auth_error:
                raise state.auth_error

        def get_transport(self):
            return self.transport

        def close(self):
            self.closed = True
            self.transport.is_active.return_value = False

    monkeypatch.setattr(remote.paramiko, "SSHClient", Client)
    state.service = remote.RemoteWorkspaceService()
    state.payload = {"host": "host.test", "username": "dev", "root": ROOT, "host_key_fingerprint": FINGERPRINT}
    yield state
    state.service.close_all()


def connected(ssh, **overrides):
    config = ssh.service.connect(7, {**ssh.payload, **overrides})
    return config, ssh.service.get(config)


@contextmanager
def error_code(code):
    with pytest.raises(remote.RemoteWorkspaceError) as error:
        yield error
    assert error.value.code == code


def test_unknown_host_requires_confirmation_before_authentication(ssh):
    with error_code("host_key_confirmation_required") as error:
        connected(ssh, host_key_fingerprint="", password="secret")
    assert error.value.status == 409
    assert error.value.data == {"host_key_fingerprint": FINGERPRINT}
    assert ssh.clients[0].auth_attempts == 0
    assert ssh.clients[0].closed
    assert not ssh.service._connections


def test_wrong_pin_rejected_before_authentication_even_with_known_host(ssh):
    ssh.known = True
    with error_code("host_key_mismatch"):
        connected(ssh, host_key_fingerprint="SHA256:" + "A" * 43)
    assert ssh.clients[0].auth_attempts == 0


def test_verified_known_host_accepted_and_pinned_for_reconnect(ssh):
    ssh.known = True
    config, connection = connected(ssh, host_key_fingerprint="", root="")
    assert config["root"] == "/home/dev"
    assert config["host_key_fingerprint"] == FINGERPRINT
    assert ssh.clients[0].loaded
    ssh.clients[0].transport.is_active.return_value = False
    connection.list_directory(root=config["root"])
    assert not ssh.clients[1].loaded
    assert ssh.clients[1].policy.expected == FINGERPRINT


def test_password_key_passphrase_are_memory_only_and_pool_is_reused(ssh):
    config, connection = connected(ssh, password="secret", passphrase="phrase", key_filename="C:/keys/id_ed25519")
    assert set(config) == {"connection_id", "host", "port", "username", "root", "host_key_fingerprint", "key_filename"}
    assert ssh.service.get(config) is connection
    assert ssh.clients[0].kwargs["password"] == "secret"
    assert ssh.clients[0].kwargs["passphrase"] == "phrase"
    assert ssh.clients[0].kwargs["key_filename"] == "C:/keys/id_ed25519"
    assert ssh.clients[0].kwargs["allow_agent"] and ssh.clients[0].kwargs["look_for_keys"]
    connection.list_directory(root=ROOT)
    connection.read_file("file.txt", ROOT)
    assert "." not in ssh.clients[0].sftp.stat_paths
    assert len(ssh.clients) == 1
    ssh.clients[0].open_sftp.assert_called_once()
    ssh.clients[0].transport.set_keepalive.assert_called_once_with(30)
    ssh.service.close_all()
    assert connection._password is connection._passphrase is None
    assert ssh.clients[0].closed and ssh.clients[0].sftp.closed
    with error_code("remote_connection_closed"):
        connection.list_directory(root=ROOT)


def test_draft_ownership_and_connection_identity(ssh):
    config, connection = connected(ssh)
    assert ssh.service.connection_config(config["connection_id"], 7) == config
    with error_code("remote_connection_not_found"):
        ssh.service.connection_config(config["connection_id"], 8)
    with error_code("remote_connection_mismatch"):
        ssh.service.get({**config, "host": "attacker.test"})
    assert ssh.service.get(config) is connection


def test_bind_root_returns_independent_verified_config(ssh):
    config, _ = connected(ssh)
    bound = ssh.service.bind_root(config, "/outside")
    assert bound["root"] == "/outside" and config["root"] == ROOT
    with error_code("not_a_directory"):
        ssh.service.bind_root(config, ROOT + "/file.txt")


def test_restart_uses_keys_or_agent_and_requires_missing_secrets(ssh):
    config, _ = connected(ssh, password="secret")
    ssh.service.close_all()
    connection = ssh.service.get(config)
    assert len(ssh.clients) == 1  # Restoring a model does not perform network I/O.
    ssh.auth_error = paramiko.AuthenticationException("denied")
    with error_code("remote_auth_required"):
        connection.list_directory(root=ROOT)
    assert ssh.clients[-1].kwargs["password"] is None
    assert ssh.clients[-1].kwargs["allow_agent"]
    ssh.auth_error = None
    restored = ssh.service.connect(7, {**config, "password": "fresh-secret"}, connection_id=config["connection_id"])
    assert restored == config
    assert ssh.clients[-1].kwargs["password"] == "fresh-secret"
    assert ssh.service.get(restored).read_file("file.txt", ROOT)["content"] == "one\ntwo\n"


@pytest.mark.parametrize("changed", [{"host": "other.test"}, {"root": "/outside"}])
def test_reauthentication_cannot_change_pooled_identity(ssh, changed):
    config, _ = connected(ssh)
    with error_code("remote_connection_mismatch"):
        ssh.service.connect(7, {**config, **changed}, connection_id=config["connection_id"])
    assert len(ssh.clients) == 1


def test_authorized_collaborator_reauthenticates_without_taking_draft_ownership(ssh):
    config, old = connected(ssh)
    config = ssh.service.bind_root(config, "/outside")
    restored = ssh.service.connect(8, {**config, "password": "fresh"}, connection_id=config["connection_id"])
    assert restored == config and old._closed
    assert ssh.service.connection_config(config["connection_id"], 7) == restored
    with error_code("remote_connection_not_found"):
        ssh.service.connection_config(config["connection_id"], 8)


def test_reauthentication_rejects_saved_root_retargeted_through_symlink(ssh):
    config, _ = connected(ssh)
    ssh.nodes[ROOT] = {"mode": stat.S_IFLNK | 0o777, "link": "/outside"}
    with error_code("remote_connection_mismatch"):
        ssh.service.connect(8, config, connection_id=config["connection_id"])
    assert ssh.clients[-1].closed


@pytest.mark.parametrize("reauth", [False, True])
def test_slow_authentication_does_not_hold_pool_lock(ssh, reauth):
    config, existing = connected(ssh)
    entered, release = threading.Event(), threading.Event()

    def authenticate(kwargs):
        entered.set()
        assert release.wait(2)

    ssh.on_connect = authenticate
    with ThreadPoolExecutor(max_workers=2) as pool:
        login = pool.submit(ssh.service.connect, 8, config if reauth else ssh.payload,
                            connection_id=config["connection_id"] if reauth else "")
        try:
            assert entered.wait(1)
            access = pool.submit(lambda: (ssh.service.get(config), ssh.service.connection_config(config["connection_id"], 7)))
            assert access.result(timeout=0.5) == (existing, config)
        finally:
            release.set()
        assert login.result(timeout=1)["host"] == config["host"]


def test_close_all_discards_inflight_authentication(ssh):
    config, _ = connected(ssh)
    entered, release = threading.Event(), threading.Event()

    def authenticate(kwargs):
        entered.set()
        assert release.wait(2)

    ssh.on_connect = authenticate
    with ThreadPoolExecutor(max_workers=1) as pool:
        login = pool.submit(ssh.service.connect, 8, ssh.payload)
        try:
            assert entered.wait(1)
            ssh.service.close_all()
        finally:
            release.set()
        with error_code("remote_connection_changed"):
            login.result(timeout=1)
    assert not ssh.service._connections and all(client.closed for client in ssh.clients)


def test_closed_channel_reconnects_once_without_network_probe(ssh):
    config, connection = connected(ssh, password="secret")
    ssh.clients[0].sftp.channel.closed = True
    assert connection.read_file("file.txt", ROOT)["content"] == "one\ntwo\n"
    assert len(ssh.clients) == 2 and ssh.clients[0].closed
    assert ssh.clients[1].kwargs["password"] == "secret"
    assert "." not in ssh.clients[1].sftp.stat_paths
    ssh.clients[1].transport.is_active.return_value = False
    ssh.auth_error = paramiko.AuthenticationException("denied")
    with error_code("remote_auth_failed"):
        connection.read_file("file.txt", ROOT)
    assert len(ssh.clients) == 3


def test_sftp_subsystem_acknowledgement_timeout_is_bounded(ssh, monkeypatch):
    _, connection = connected(ssh)
    client = ssh.clients[0]
    connection._sftp = None
    stopped = threading.Event()
    original_close = client.close

    def close():
        original_close()
        stopped.set()

    def stalled():
        stopped.wait(1)
        raise paramiko.SSHException("Subsystem closed")

    monkeypatch.setattr(remote, "IO_TIMEOUT", 0.02)
    client.close = close
    client.open_sftp.side_effect = stalled
    with error_code("remote_timeout"):
        connection.list_directory(root=ROOT)
    assert stopped.is_set() and len(ssh.clients) == 1


@pytest.mark.parametrize("path", ["../outside/secret", "/outside/secret", ROOT + "-other/file", "link/secret", "link/missing", "deep/../secret"])
def test_paths_and_symlinks_cannot_escape_root(ssh, path):
    ssh.nodes[ROOT + "/link"] = {"mode": stat.S_IFLNK | 0o777, "link": "/outside"}
    ssh.nodes[ROOT + "/deep"] = {"mode": stat.S_IFLNK | 0o777, "link": "/outside/deep"}
    _, connection = connected(ssh)
    with error_code("forbidden_path"):
        connection.write_file(path, "changed", ROOT)
    assert ssh.nodes["/outside/secret"]["data"] == b"secret"


def test_symlinks_inside_root_work_and_outside_links_are_not_listed(ssh):
    ssh.nodes[ROOT + "/inside"] = {"mode": stat.S_IFLNK | 0o777, "link": "file.txt"}
    ssh.nodes[ROOT + "/outside"] = {"mode": stat.S_IFLNK | 0o777, "link": "/outside/secret"}
    _, connection = connected(ssh)
    assert connection.read_file("inside", ROOT)["content"] == "one\ntwo\n"
    listing = connection.list_directory(root=ROOT)
    assert listing == {"working_dir": ROOT, "is_virtual_root": False, "entries": [
        {"name": "file.txt", "is_dir": False, "size": 8}, {"name": "inside", "is_dir": False, "size": 8},
    ]}


def test_changed_root_symlink_is_rejected(ssh):
    _, connection = connected(ssh)
    ssh.nodes[ROOT] = {"mode": stat.S_IFLNK | 0o777, "link": "/outside"}
    with error_code("forbidden_path"):
        connection.list_directory(root=ROOT)


def test_read_ranges_utf8_and_size_limit(ssh, monkeypatch):
    _, connection = connected(ssh)
    result = connection.read_file("file.txt", ROOT, offset=2, limit=1)
    assert result["content"] == "two\n" and not result["is_full_content"]
    assert result["last_modified_ns"] == ""
    ssh.nodes[ROOT + "/file.txt"]["data"] = b"\xff\x00"
    with error_code("unsupported_encoding"):
        connection.read_file("file.txt", ROOT)
    monkeypatch.setattr(remote, "MAX_TEXT_BYTES", 1)
    with error_code("file_too_large"):
        connection.read_file("file.txt", ROOT)
    with error_code("file_too_large"):
        connection.write_file("file.txt", "big", ROOT)


def test_partial_read_stops_after_requested_lines_in_bounded_chunks(ssh):
    ssh.nodes[ROOT + "/file.txt"]["data"] = b"short\n" * 300000
    _, connection = connected(ssh)
    result = connection.read_file("file.txt", ROOT, offset=3, limit=2)
    assert result["content"] == "short\nshort\n"
    assert not result["is_full_content"] and result["total_lines"] is None
    assert result["last_modified_ns"] == ""
    reads = ssh.clients[0].sftp.reads
    assert sum(count for _, count in reads) <= remote.READ_CHUNK_BYTES
    assert all(0 < requested <= remote.READ_CHUNK_BYTES for requested, _ in reads)
    with error_code("file_version_conflict"):
        connection.write_file("file.txt", result["content"], ROOT, result["last_modified_ns"])


@pytest.mark.parametrize("raw, offset, limit, content, full", [
    (b"", 1, 1, "", True),
    (b"one\n", 1, 1, "one\n", True),
    (b"one\nlast", 1, 1, "one\n", False),
    (b"one\nlast", 1, 2, "one\nlast", True),
    (b"one\nlast\n", 2, 0, "last\n", False),
    (b"one\nlast\n", 3, 1, "", False),
    (b"one\nlast\n", 1, 5, "one\nlast\n", True),
])
def test_line_ranges_report_full_content_only_when_response_contains_whole_file(ssh, raw, offset, limit, content, full):
    ssh.nodes[ROOT + "/file.txt"]["data"] = raw
    _, connection = connected(ssh)
    result = connection.read_file("file.txt", ROOT, offset=offset, limit=limit)
    assert result["content"] == content and result["is_full_content"] is full
    assert result["last_modified_ns"] == ("sha256:" + hashlib.sha256(raw).hexdigest() if full else "")


def test_chunk_boundaries_preserve_utf8_bom_and_crlf(ssh, monkeypatch):
    raw = b"\xef\xbb\xbf" + "你\r\n好\r\n末尾".encode("utf-8")
    ssh.nodes[ROOT + "/file.txt"]["data"] = raw
    monkeypatch.setattr(remote, "READ_CHUNK_BYTES", 5)
    _, connection = connected(ssh)
    head = connection.read_file("file.txt", ROOT, limit=1)
    assert head["content"] == "你\r\n" and not head["is_full_content"]
    result = connection.read_file("file.txt", ROOT)
    assert result["content"] == "你\r\n好\r\n末尾" and result["encoding"] == "utf-8-sig"
    assert result["last_modified_ns"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    saved = connection.write_file("file.txt", result["content"], ROOT, result["last_modified_ns"], encoding=result["encoding"])
    assert saved["last_modified_ns"] == result["last_modified_ns"]


def test_full_read_token_detects_external_same_second_same_size_edit(ssh):
    _, connection = connected(ssh)
    original = connection.read_file("file.txt", ROOT)
    ssh.nodes[ROOT + "/file.txt"]["data"] = b"ONE\nTWO\n"
    assert ssh.nodes[ROOT + "/file.txt"]["mtime"] == 100
    with error_code("file_version_conflict"):
        connection.write_file("file.txt", "editor save", ROOT, original["last_modified_ns"])
    assert ssh.nodes[ROOT + "/file.txt"]["data"] == b"ONE\nTWO\n"
    assert ssh.clients[0].sftp.rename_calls == 0
    assert not any(".orbit-" in path for path in ssh.nodes)


def test_read_rejects_special_files_before_opening(ssh):
    ssh.nodes[ROOT + "/pipe"] = {"mode": stat.S_IFIFO | 0o600}
    _, connection = connected(ssh)
    ssh.clients[0].sftp.open = Mock(side_effect=AssertionError("Must not open a FIFO"))
    with error_code("not_a_file"):
        connection.read_file("pipe", ROOT)


def test_target_changed_during_upload_is_not_overwritten(ssh, monkeypatch):
    _, connection = connected(ssh)
    token = connection.read_file("file.txt", ROOT)["last_modified_ns"]
    original_write = MemoryFile.write

    def write_and_modify(file, value):
        result = original_write(file, value)
        ssh.nodes[ROOT + "/file.txt"]["data"] = b"external"
        return result

    monkeypatch.setattr(MemoryFile, "write", write_and_modify)
    with error_code("file_version_conflict"):
        connection.write_file("file.txt", "my edit", ROOT, token)
    assert ssh.nodes[ROOT + "/file.txt"]["data"] == b"external"
    assert ssh.clients[0].sftp.rename_calls == 0
    assert not any(".orbit-" in p for p in ssh.nodes)


def test_write_uses_content_version_without_advancing_remote_mtime(ssh):
    _, connection = connected(ssh)
    token = connection.read_file("file.txt", ROOT)["last_modified_ns"]
    with error_code("file_version_conflict"):
        connection.write_file("file.txt", "wrong", ROOT, "99000000000")
    assert ssh.clients[0].sftp.rename_calls == 0
    result = connection.write_file("file.txt", "new", ROOT, token)
    assert result["last_modified_ns"] != token
    assert ssh.nodes[ROOT + "/file.txt"]["mtime"] == 100
    assert ssh.nodes[ROOT + "/file.txt"]["mode"] == stat.S_IFREG | 0o640
    after = connection.read_file("file.txt", ROOT)
    assert after["content"] == "new" and after["last_modified_ns"] == result["last_modified_ns"]
    with error_code("file_version_conflict"):
        connection.write_file("file.txt", "stale", ROOT, token)
    assert not any(".orbit-" in p for p in ssh.nodes)


def test_concurrent_saves_with_same_version_have_one_winner(ssh):
    _, connection = connected(ssh)
    token = connection.read_file("file.txt", ROOT)["last_modified_ns"]

    def save(text):
        try:
            connection.write_file("file.txt", text, ROOT, token)
            return "saved"
        except remote.RemoteWorkspaceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["first", "second"]))
    assert sorted(results) == ["file_version_conflict", "saved"]
    assert ssh.clients[0].sftp.rename_calls == 1


def test_unsupported_atomic_replacement_preserves_original(ssh):
    _, connection = connected(ssh)
    ssh.clients[0].sftp.atomic_supported = False
    with error_code("atomic_replace_unsupported"):
        connection.write_file("file.txt", "new", ROOT)
    assert ssh.nodes[ROOT + "/file.txt"]["data"] == b"one\ntwo\n"
    assert not any(".orbit-" in p for p in ssh.nodes)


def test_lost_mutation_response_is_never_replayed(ssh):
    _, connection = connected(ssh)
    ssh.clients[0].sftp.fail_after_rename = True
    with error_code("remote_disconnected"):
        connection.write_file("file.txt", "new", ROOT)
    assert ssh.nodes[ROOT + "/file.txt"]["data"] == b"new"
    assert ssh.clients[0].sftp.rename_calls == 1
    assert len(ssh.clients) == 1


def test_create_and_mkdir_do_not_overwrite(ssh):
    _, connection = connected(ssh)
    connection.mkdir("folder", root=ROOT)
    connection.create_file("folder/new.txt", "hello", root=ROOT)
    with error_code("path_exists"):
        connection.create_file("folder/new.txt", "bad", root=ROOT)
    assert connection.read_file("folder/new.txt", ROOT)["content"] == "hello"


def test_terminal_channels_share_transport_but_close_independently(ssh):
    from bot.platform.terminal import PtyWrapper

    _, connection = connected(ssh)
    first = connection.open_terminal(ROOT)
    second = connection.open_terminal(ROOT, cols=80, rows=24)
    wrapper = PtyWrapper(first, is_pty=True, read_timeout_supported=True)
    wrapper.write(b"hello")
    assert wrapper.resize(90, 30)
    assert first._channel.sent == b"hello"
    assert first._channel.size == {"width": 90, "height": 30}
    assert wrapper.read(timeout=1) == b""
    first._channel.stdout.extend(b"remote output")
    assert wrapper.read(timeout=1) == b"remote output"
    wrapper.close()
    assert not first.isalive() and second.isalive()
    assert not ssh.clients[0].closed
    assert first.pid == 0
    second.terminate()


def test_command_drains_both_streams_bounds_output_and_quotes_root(ssh):
    root = ROOT + "/a'b"
    ssh.nodes[root] = {"mode": stat.S_IFDIR | 0o755}
    _, connection = connected(ssh)
    channel = ssh.next_channel = Channel(stdout=b"hello", stderr=b"warning")
    result = connection.execute("printf hello", root, max_output=8)
    assert result == {"stdout": "hello", "stderr": "war", "returncode": 0, "output_truncated": True}
    assert channel.commands == ["cd '/home/dev/project/a'\"'\"'b' && exec /bin/sh -c 'printf hello'"]
    assert channel.closed and not ssh.clients[0].closed


def test_command_timeout_closes_only_channel_and_does_not_retry(ssh):
    _, connection = connected(ssh)
    channel = ssh.next_channel = Channel(stdout=b"partial", running=True)
    with error_code("remote_timeout") as error:
        connection.execute("sleep 10", ROOT, timeout=0.02)
    assert error.value.data["stdout"] == "partial"
    assert channel.closed and len(channel.commands) == 1
    assert len(ssh.clients) == 1 and not ssh.clients[0].closed


def test_command_acknowledgement_timeout_is_bounded(ssh):
    _, connection = connected(ssh)
    channel = ssh.next_channel = Channel(running=True)

    def stalled(command):
        channel.commands.append(command)
        stopped.wait(1)
        raise paramiko.SSHException("Channel closed")

    stopped = threading.Event()
    channel.exec_command = stalled
    channel.close = lambda: (setattr(channel, "closed", True), stopped.set())
    with error_code("remote_timeout"):
        connection.execute("touch file", ROOT, timeout=0.02)
    assert stopped.is_set() and len(channel.commands) == 1


def test_normalizer_strips_secrets_and_singleton_is_shared(ssh):
    config, _ = connected(ssh)
    assert remote.normalize_remote_workspace({**config, "password": "secret", "passphrase": "phrase", "extra": {"secret": "x"}}) == config
    assert remote.normalize_remote_workspace(None) == {}
    assert remote.get_remote_workspace_service() is remote.get_remote_workspace_service()


@pytest.mark.parametrize("override", [
    {"host": ""}, {"host": "bad\nhost"}, {"username": ""}, {"port": 0}, {"port": True},
    {"port": 65536}, {"root": "relative"}, {"root": "C:/local"}, {"host_key_fingerprint": ""},
    {"host_key_fingerprint": "SHA256:bad"}, {"connection_id": "../other"},
])
def test_normalizer_rejects_invalid_persisted_configs(ssh, override):
    config, _ = connected(ssh)
    with error_code("invalid_remote_workspace"):
        remote.normalize_remote_workspace({**config, **override})
