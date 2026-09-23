"""POSIX SSH/SFTP transport. Public configs contain no authentication secrets.

SFTP operations are serialized per connection; exec and PTY channels are independent.
Only locally known stale connections reconnect. Submitted operations are never replayed.
Root checks constrain file APIs; an interactive shell/command is not a filesystem jail.

For complete text responses, last_modified_ns is an opaque ``sha256:<hex>`` token
of the exact file bytes, not a timestamp. Pass it unchanged as expected_mtime_ns.
Partial responses have an empty token and must be fully read before an editor save.
"""

from __future__ import annotations

import base64
import codecs
from contextlib import contextmanager, suppress
import errno
import hashlib
import os
import posixpath
import re
import shlex
import socket
import stat
import threading
import time
from typing import Any, Iterator
import uuid

import paramiko


IO_TIMEOUT = 15
MAX_TEXT_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 32768
MAX_COMMAND_OUTPUT = 1024 * 1024
MAX_DIRECTORY_ENTRIES = 10000
_IDENTITY_FIELDS = ("host", "port", "username", "host_key_fingerprint", "key_filename")


class RemoteWorkspaceError(Exception):
    def __init__(self, status: int, code: str, message: str, data: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = dict(data or {})


def _invalid(message: str) -> None:
    raise RemoteWorkspaceError(400, "invalid_remote_workspace", message)


def _string(value: Any, field: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        _invalid(f"Invalid {field}")
    if len(value) > 4096 or (required and not value.strip()):
        _invalid(f"Invalid {field}")
    return value


def _config(value: dict, *, verified: bool) -> dict:
    if not isinstance(value, dict):
        _invalid("Remote workspace must be an object")
    host = _string(value.get("host"), "host", required=True).strip()
    if any(c.isspace() or c in "/\\@" for c in host):
        _invalid("Invalid host")
    username = _string(value.get("username"), "username", required=True).strip()
    port_value = value.get("port", 22)
    if isinstance(port_value, bool) or not re.fullmatch(r"[0-9]{1,5}", str(port_value)):
        _invalid("Invalid SSH port")
    port = int(port_value)
    if not 1 <= port <= 65535:
        _invalid("Invalid SSH port")
    connection_id = _string(value.get("connection_id"), "connection_id", required=verified)
    if connection_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", connection_id):
        _invalid("Invalid connection ID")
    fingerprint = _string(value.get("host_key_fingerprint"), "host_key_fingerprint", required=verified)
    if fingerprint:
        if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}=?", fingerprint):
            _invalid("Expected an SSH SHA256 host key fingerprint")
        fingerprint = fingerprint.rstrip("=")
    root = _string(value.get("root"), "root", required=verified)
    if root and (not root.startswith("/") or root.startswith("//")):
        _invalid("Remote root must be an absolute POSIX path")
    if root:
        root = posixpath.normpath(root)
    return {
        "connection_id": connection_id,
        "host": host,
        "port": port,
        "username": username,
        "root": root,
        "host_key_fingerprint": fingerprint,
        "key_filename": _string(value.get("key_filename"), "key_filename"),
    }


def normalize_remote_workspace(value: Any) -> dict:
    """Validate a persisted config and whitelist public fields; None/{} mean local."""
    if value is None or value == {}:
        return {}
    return _config(value, verified=True)


def _fingerprint(key: paramiko.PKey) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")


class _HostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected: str):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        actual = _fingerprint(key)
        data = {"host_key_fingerprint": actual}
        if not self.expected:
            raise RemoteWorkspaceError(409, "host_key_confirmation_required", "Confirm the SSH host key fingerprint", data)
        if actual != self.expected:
            raise RemoteWorkspaceError(409, "host_key_mismatch", "The SSH host key has changed", data)


@contextmanager
def _remote_errors() -> Iterator[None]:
    try:
        yield
    except RemoteWorkspaceError:
        raise
    except (socket.timeout, TimeoutError) as exc:
        raise RemoteWorkspaceError(504, "remote_timeout", "The remote operation timed out") from exc
    except (paramiko.SSHException, EOFError, ConnectionError) as exc:
        raise RemoteWorkspaceError(502, "remote_disconnected", "The SSH connection was interrupted; operation was not retried") from exc
    except OSError as exc:
        code, status = {
            errno.ENOENT: ("path_not_found", 404),
            errno.EACCES: ("permission_denied", 403),
            errno.EPERM: ("permission_denied", 403),
            errno.EEXIST: ("path_exists", 409),
            errno.ENOTDIR: ("not_a_directory", 400),
        }.get(exc.errno, ("remote_io_error", 502))
        raise RemoteWorkspaceError(status, code, "Remote filesystem operation failed") from exc


def _version(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _signature(attrs) -> tuple | None:
    return (attrs.st_mtime, attrs.st_size, attrs.st_mode) if attrs is not None else None


def _file_chunks(handle, attrs):
    """Read bounded chunks, stopping at the observed size and checking for short reads."""
    fetched = 0
    while True:
        chunk = handle.read(min(READ_CHUNK_BYTES, attrs.st_size - fetched)) if fetched < attrs.st_size else b""
        fetched += len(chunk)
        if fetched > MAX_TEXT_BYTES:
            raise RemoteWorkspaceError(413, "file_too_large", "Remote text file is too large")
        complete = fetched == attrs.st_size
        if not chunk and not complete:
            raise RemoteWorkspaceError(409, "file_version_conflict", "File changed while reading")
        yield chunk, complete
        if complete:
            return


def _inside(root: str, path: str) -> None:
    if path != root and not path.startswith(root.rstrip("/") + "/"):
        raise RemoteWorkspaceError(403, "forbidden_path", "Path escapes the remote workspace root")


def _absolute(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "\x00" in path:
        raise RemoteWorkspaceError(400, "invalid_path", "Expected an absolute POSIX path")
    return posixpath.normpath(path)


class RemoteConnection:
    def __init__(self, config: dict, *, password: str | None = None, passphrase: str | None = None):
        self.config = dict(config)
        self._password = password
        self._passphrase = passphrase
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._lock = threading.RLock()
        self._closed = False

    def _disconnect(self) -> None:
        sftp, client = self._sftp, self._client
        self._sftp = self._client = None
        for resource in (sftp, client):
            if resource is not None:
                with suppress(Exception):
                    resource.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._disconnect()
            self._password = self._passphrase = None

    def _connect(self) -> None:
        self._disconnect()
        client = paramiko.SSHClient()
        try:
            expected = self.config["host_key_fingerprint"]
            if not expected:
                client.load_system_host_keys()
                if os.path.isfile("/etc/ssh/ssh_known_hosts"):
                    client.load_system_host_keys("/etc/ssh/ssh_known_hosts")
            client.set_missing_host_key_policy(_HostKeyPolicy(expected))
            client.connect(
                hostname=self.config["host"], port=self.config["port"], username=self.config["username"],
                password=self._password, passphrase=self._passphrase,
                key_filename=self.config["key_filename"] or None,
                allow_agent=True, look_for_keys=True,
                timeout=IO_TIMEOUT, banner_timeout=IO_TIMEOUT, auth_timeout=IO_TIMEOUT,
                channel_timeout=IO_TIMEOUT,
            )
            transport = client.get_transport()
            transport.set_keepalive(30)
            self.config["host_key_fingerprint"] = _fingerprint(transport.get_remote_server_key())
            self._client = client
        except paramiko.BadHostKeyException as exc:
            client.close()
            raise RemoteWorkspaceError(409, "host_key_mismatch", "The SSH host key has changed", {
                "host_key_fingerprint": _fingerprint(exc.key),
            }) from exc
        except (paramiko.AuthenticationException, paramiko.PasswordRequiredException) as exc:
            client.close()
            missing = self._password is None and self._passphrase is None
            raise RemoteWorkspaceError(401, "remote_auth_required" if missing else "remote_auth_failed",
                                       "SSH authentication required; passwords/passphrases are not saved" if missing else "SSH authentication failed") from exc
        except paramiko.SSHException as exc:
            client.close()
            if str(exc) == "No authentication methods available":
                raise RemoteWorkspaceError(401, "remote_auth_required", "SSH authentication required; passwords/passphrases are not saved") from exc
            raise
        except Exception:
            client.close()
            raise

    def _ensure(self) -> None:
        if self._closed:
            raise RemoteWorkspaceError(410, "remote_connection_closed", "Remote connection has been closed")
        transport = self._client.get_transport() if self._client else None
        if not transport or not transport.is_active() or not transport.is_authenticated():
            self._connect()
        elif self._sftp is not None and self._sftp.get_channel().closed:
            self._connect()
        if self._sftp is None:
            # Subsystem acknowledgement does not honor Channel.settimeout in Paramiko.
            expired = threading.Event()

            def expire():
                expired.set()
                self._client.close()

            timer = threading.Timer(IO_TIMEOUT, expire)
            timer.daemon = True
            timer.start()
            try:
                self._sftp = self._client.open_sftp()
                self._sftp.get_channel().settimeout(IO_TIMEOUT)
            except Exception as exc:
                if expired.is_set():
                    raise RemoteWorkspaceError(504, "remote_timeout", "Opening SFTP timed out") from exc
                raise
            finally:
                timer.cancel()

    @contextmanager
    def _operation(self):
        with self._lock, _remote_errors():
            self._ensure()
            yield self._sftp

    def canonical_root(self, root: str = "") -> str:
        with self._operation() as sftp:
            path = _absolute(sftp.normalize(root or "."))
            if not stat.S_ISDIR(sftp.stat(path).st_mode):
                raise RemoteWorkspaceError(400, "not_a_directory", "Remote root is not a directory")
            return path

    def _resolve(self, path: str, root: str, *, missing: bool = False) -> str:
        root = _absolute(root)
        if not isinstance(path, str) or "\x00" in path:
            raise RemoteWorkspaceError(400, "invalid_path", "Invalid remote path")
        if _absolute(self._sftp.normalize(root)) != root:
            raise RemoteWorkspaceError(403, "forbidden_path", "Remote root has changed")
        candidate = posixpath.join(root, path or ".")
        _inside(root, _absolute(candidate))
        try:
            self._sftp.lstat(candidate)
        except OSError as exc:
            if not missing or exc.errno != errno.ENOENT:
                raise
            parent = _absolute(self._sftp.normalize(posixpath.dirname(candidate)))
            resolved = posixpath.join(parent, posixpath.basename(candidate))
        else:
            resolved = _absolute(self._sftp.normalize(candidate))
        _inside(root, resolved)
        return resolved

    def list_directory(self, path: str = "", *, root: str) -> dict:
        with self._operation() as sftp:
            directory = self._resolve(path, root)
            entries = []
            for index, attrs in enumerate(sftp.listdir_iter(directory, read_aheads=1)):
                if index >= MAX_DIRECTORY_ENTRIES:
                    raise RemoteWorkspaceError(413, "directory_too_large", "Remote directory has too many entries")
                name = attrs.filename
                if name in {"", ".", ".."} or "/" in name or "\x00" in name:
                    continue
                if stat.S_ISLNK(attrs.st_mode):
                    try:
                        target = self._resolve(posixpath.join(directory, name), root)
                        attrs = sftp.stat(target)
                    except (RemoteWorkspaceError, OSError):
                        continue
                is_dir = stat.S_ISDIR(attrs.st_mode)
                item = {"name": name, "is_dir": is_dir}
                if not is_dir:
                    item["size"] = attrs.st_size
                entries.append(item)
            entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
            return {"working_dir": directory, "entries": entries, "is_virtual_root": False}

    def read_file(self, path: str, root: str, offset: int = 1, limit: int = 0) -> dict:
        """Read a line range; only full content receives a token suitable for editor saves.

        total_lines is None when the read stops before EOF. At most one bounded
        chunk is fetched beyond the requested lines; no tail scan is performed.
        """
        if not isinstance(offset, int) or not isinstance(limit, int) or offset < 1 or limit < 0:
            raise RemoteWorkspaceError(400, "invalid_range", "Invalid line range")
        with self._operation() as sftp:
            resolved = self._resolve(path, root)
            self._check_text_file(sftp.stat(resolved))
            with sftp.open(resolved, "rb") as handle:
                attrs = handle.stat()
                self._check_text_file(attrs)
                digest = hashlib.sha256()
                decoder = codecs.getincrementaldecoder("utf-8-sig")()
                lines, pending, encoding = [], "", "utf-8"
                stop_after = offset - 1 + limit if limit else 0
                try:
                    for chunk, complete in _file_chunks(handle, attrs):
                        if not lines and not pending and chunk.startswith(b"\xef\xbb\xbf"):
                            encoding = "utf-8-sig"
                        digest.update(chunk)
                        text = pending + decoder.decode(chunk, final=complete)
                        if "\x00" in text:
                            raise UnicodeError()
                        parts = text.splitlines(keepends=True)
                        pending = ""
                        if parts and not complete and (
                            not parts[-1].endswith(("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"))
                            or parts[-1].endswith("\r")
                        ):
                            pending = parts.pop()
                        lines.extend(parts)
                        if stop_after and len(lines) >= stop_after:
                            break
                except UnicodeError as exc:
                    raise RemoteWorkspaceError(400, "unsupported_encoding", "Only UTF-8 text files are supported") from exc
                if _signature(handle.stat()) != _signature(attrs):
                    raise RemoteWorkspaceError(409, "file_version_conflict", "File changed while reading")
            selected = lines[offset - 1:offset - 1 + limit] if limit else lines[offset - 1:]
            full_content = complete and offset == 1 and (not limit or limit >= len(lines))
            return {
                "filename": path, "path": resolved, "mode": "cat", "content": "".join(selected),
                "working_dir": root, "size": attrs.st_size, "file_size_bytes": attrs.st_size,
                "last_modified_ns": "sha256:" + digest.hexdigest() if full_content else "", "encoding": encoding,
                "is_full_content": full_content,
                "total_lines": len(lines) if complete else None, "offset": offset,
            }

    def _file_version(self, path: str, attrs) -> str:
        """Hash the current file immediately before replacement, without decoding it."""
        with self._sftp.open(path, "rb") as handle:
            if _signature(handle.stat()) != _signature(attrs):
                raise RemoteWorkspaceError(409, "file_version_conflict", "File changed while saving")
            digest = hashlib.sha256()
            for chunk, _ in _file_chunks(handle, attrs):
                digest.update(chunk)
            if _signature(handle.stat()) != _signature(attrs):
                raise RemoteWorkspaceError(409, "file_version_conflict", "File changed while saving")
            return "sha256:" + digest.hexdigest()

    @staticmethod
    def _check_text_file(attrs) -> None:
        if not stat.S_ISREG(attrs.st_mode):
            raise RemoteWorkspaceError(400, "not_a_file", "Path is not a regular file")
        if attrs.st_size > MAX_TEXT_BYTES:
            raise RemoteWorkspaceError(413, "file_too_large", "Remote text file is too large")

    def _stat_optional(self, path: str):
        try:
            return self._sftp.stat(path)
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise
            return None

    def write_file(self, path: str, content: str, root: str, expected_mtime_ns: int | str | None = None,
                   *, encoding: str = "utf-8") -> dict:
        """Save text; expected_mtime_ns must be a full read's opaque content token.

        None requests an unconditional save. Empty, timestamp, and stale tokens
        fail with file_version_conflict. Remote mtimes are never synthesized.
        """
        return self._write_file(path, content, root, expected_mtime_ns, encoding=encoding)

    def create_file(self, path: str, content: str = "", *, root: str) -> dict:
        return self._write_file(path, content, root, None, create_only=True)

    def _write_file(self, path, content, root, expected_mtime_ns, *, encoding="utf-8", create_only=False):
        if not isinstance(content, str) or "\x00" in content or encoding not in {"utf-8", "utf-8-sig"}:
            raise RemoteWorkspaceError(400, "unsupported_encoding", "Only UTF-8 text files are supported")
        try:
            raw = content.encode(encoding)
        except UnicodeError as exc:
            raise RemoteWorkspaceError(400, "unsupported_encoding", "Content is not valid UTF-8 text") from exc
        if len(raw) > MAX_TEXT_BYTES:
            raise RemoteWorkspaceError(413, "file_too_large", "Remote text file is too large")
        with self._operation() as sftp:
            resolved = self._resolve(path, root, missing=True)
            previous = self._stat_optional(resolved)
            if create_only and previous is not None:
                raise RemoteWorkspaceError(409, "path_exists", "Path already exists")
            if previous is not None:
                self._check_text_file(previous)
            if expected_mtime_ns is not None and (
                previous is None or not isinstance(expected_mtime_ns, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_mtime_ns)
            ):
                raise RemoteWorkspaceError(409, "file_version_conflict", "Fully reopen the file before saving")
            temporary = posixpath.join(posixpath.dirname(resolved), ".orbit-" + uuid.uuid4().hex + ".tmp")
            created = False
            try:
                with sftp.open(temporary, "wx") as handle:
                    created = True
                    handle.chmod(stat.S_IMODE(previous.st_mode) if previous else 0o600)
                    handle.write(raw)
                    handle.flush()
                if self._resolve(path, root, missing=True) != resolved or _signature(self._stat_optional(resolved)) != _signature(previous):
                    raise RemoteWorkspaceError(409, "file_version_conflict", "File changed while saving")
                if expected_mtime_ns is not None and self._file_version(resolved, previous) != expected_mtime_ns:
                    raise RemoteWorkspaceError(409, "file_version_conflict", "File content has changed; reopen it before saving")
                if previous is None:
                    sftp.rename(temporary, resolved)  # Standard SFTP rename refuses overwrite.
                else:
                    try:
                        sftp.posix_rename(temporary, resolved)
                    except OSError as exc:
                        if exc.errno in {errno.EOPNOTSUPP, errno.ENOSYS} or str(exc).lower() in {"operation unsupported", "operation not supported"}:
                            raise RemoteWorkspaceError(501, "atomic_replace_unsupported", "Server does not support atomic replacement") from exc
                        raise
                created = False
                return {"path": path, "size": len(raw), "file_size_bytes": len(raw),
                        "last_modified_ns": _version(raw), "encoding": encoding}
            finally:
                if created:
                    with suppress(OSError, EOFError, paramiko.SSHException):
                        sftp.remove(temporary)

    def mkdir(self, path: str, *, root: str) -> dict:
        with self._operation() as sftp:
            resolved = self._resolve(path, root, missing=True)
            sftp.mkdir(resolved)
            return {"path": resolved, "name": posixpath.basename(resolved), "working_dir": root}

    def _open_channel(self, root: str, timeout: float):
        with self._operation() as sftp:
            directory = self._resolve("", root)
            if not stat.S_ISDIR(sftp.stat(directory).st_mode):
                raise RemoteWorkspaceError(400, "not_a_directory", "Remote root is not a directory")
            channel = self._client.get_transport().open_session(timeout=min(timeout, IO_TIMEOUT))
            channel.settimeout(min(timeout, IO_TIMEOUT))
            return channel, directory

    def execute(self, command: str, root: str, timeout: float = 60, max_output: int = 65536) -> dict:
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise RemoteWorkspaceError(400, "invalid_command", "Command is required")
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise RemoteWorkspaceError(400, "invalid_timeout", "Timeout must be between 0 and 3600 seconds")
        if not isinstance(max_output, int) or not 0 < max_output <= MAX_COMMAND_OUTPUT:
            raise RemoteWorkspaceError(400, "invalid_output_limit", "Invalid command output limit")
        channel, directory = self._open_channel(root, timeout)
        expired = threading.Event()

        def expire():
            expired.set()
            channel.close()

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        output = [bytearray(), bytearray()]
        truncated = False
        try:
            with _remote_errors():
                channel.exec_command(f"cd {shlex.quote(directory)} && exec /bin/sh -c {shlex.quote(command)}")
                channel.shutdown_write()
                while True:
                    received = False
                    for index, (ready, receive) in enumerate(((channel.recv_ready, channel.recv), (channel.recv_stderr_ready, channel.recv_stderr))):
                        if ready():
                            chunk = receive(4096)
                            remaining = max_output - sum(map(len, output))
                            output[index].extend(chunk[:remaining])
                            truncated |= len(chunk) > remaining
                            received = True
                    if expired.is_set():
                        raise RemoteWorkspaceError(504, "remote_timeout", "Remote command timed out")
                    if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                        returncode = channel.recv_exit_status()
                        if returncode == -1:
                            raise RemoteWorkspaceError(502, "remote_disconnected", "Command ended without an exit status; it was not retried")
                        return {"stdout": output[0].decode("utf-8", errors="replace"),
                                "stderr": output[1].decode("utf-8", errors="replace"),
                                "returncode": returncode, "output_truncated": truncated}
                    if not received:
                        expired.wait(0.01)
        except Exception as exc:
            if expired.is_set():
                raise RemoteWorkspaceError(504, "remote_timeout", "Remote command timed out", {
                    "stdout": output[0].decode("utf-8", errors="replace"),
                    "stderr": output[1].decode("utf-8", errors="replace"),
                }) from exc
            raise
        finally:
            timer.cancel()
            channel.close()

    def open_terminal(self, root: str, cols: int = 120, rows: int = 40) -> RemoteTerminal:
        channel, directory = self._open_channel(root, IO_TIMEOUT)
        timer = threading.Timer(IO_TIMEOUT, channel.close)
        timer.daemon = True
        timer.start()
        try:
            with _remote_errors():
                channel.get_pty(term="xterm-256color", width=max(2, int(cols)), height=max(2, int(rows)))
                channel.exec_command(f'cd {shlex.quote(directory)} && exec "${{SHELL:-/bin/sh}}" -l')
                return RemoteTerminal(channel)
        except Exception:
            channel.close()
            raise
        finally:
            timer.cancel()


class RemoteTerminal:
    """Process interface for PtyWrapper(..., is_pty=True, read_timeout_supported=True)."""

    pid = 0

    def __init__(self, channel):
        self._channel = channel
        self._write_lock = threading.Lock()
        self._closed = threading.Event()

    def read(self, timeout: int = 1000) -> bytes:
        deadline = time.monotonic() + max(0, timeout) / 1000
        while not self._closed.is_set():
            if self._channel.recv_ready():
                try:
                    return self._channel.recv(4096)
                except (OSError, EOFError):
                    return b""
            if not self.isalive() or time.monotonic() >= deadline:
                break
            self._closed.wait(min(0.01, max(0, deadline - time.monotonic())))
        return b""

    def write(self, data: str) -> None:
        with self._write_lock, _remote_errors():
            self._channel.sendall(data.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        with _remote_errors():
            self._channel.resize_pty(width=max(2, int(cols)), height=max(2, int(rows)))

    def isalive(self) -> bool:
        return not self._closed.is_set() and not self._channel.closed and not self._channel.exit_status_ready()

    def terminate(self) -> None:
        self.close()

    def close(self) -> None:
        self._closed.set()
        self._channel.close()


class RemoteWorkspaceService:
    def __init__(self):
        self._lock = threading.RLock()
        self._connections: dict[str, RemoteConnection] = {}
        self._owners: dict[str, int] = {}
        self._roots: dict[str, set[str]] = {}
        self._generation = 0

    def connect(self, owner_id: int, payload: dict, *, connection_id: str = "") -> dict:
        """Create an owned draft, or reauthenticate an API-authorized persisted config.

        The connection_id keyword is reserved for callers that already authorized
        access to the saved profile; it is not taken from untrusted draft payloads.
        """
        if not isinstance(owner_id, int) or isinstance(owner_id, bool):
            _invalid("Invalid owner ID")
        config = _config(payload, verified=bool(connection_id))
        if connection_id and config["connection_id"] != connection_id:
            _invalid("Reauthentication requires the saved connection configuration")
        config["connection_id"] = connection_id or uuid.uuid4().hex
        pool_id = config["connection_id"]
        secrets = {}
        for key in ("password", "passphrase"):
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                _invalid(f"Invalid {key}")
            secrets[key] = value
        with self._lock:
            existing = self._connections.get(pool_id)
            generation = self._generation
            if existing and (
                any(existing.config[key] != config[key] for key in _IDENTITY_FIELDS)
                or config["root"] not in self._roots[pool_id]
            ):
                raise RemoteWorkspaceError(409, "remote_connection_mismatch", "Cannot change a saved connection identity or root")
        connection = RemoteConnection(config, **secrets)
        try:
            root = connection.canonical_root(config["root"])
            if connection_id and root != config["root"]:
                raise RemoteWorkspaceError(409, "remote_connection_mismatch", "Saved remote root has changed")
            connection.config["root"] = root
            public = normalize_remote_workspace(connection.config)
            with self._lock:
                if generation != self._generation or self._connections.get(pool_id) is not existing:
                    raise RemoteWorkspaceError(409, "remote_connection_changed", "Connection changed during authentication; reconnect again")
                self._connections[pool_id] = connection
                self._roots.setdefault(pool_id, set()).add(root)
                if not connection_id:
                    self._owners[pool_id] = owner_id
        except Exception:
            connection.close()
            raise
        if existing:
            existing.close()
        return public

    def connection_config(self, connection_id: str, owner_id: int) -> dict:
        with self._lock:
            if connection_id not in self._owners or self._owners[connection_id] != owner_id:
                raise RemoteWorkspaceError(404, "remote_connection_not_found", "Remote connection not found")
            return dict(self._connections[connection_id].config)

    def bind_root(self, config: dict, root: str) -> dict:
        public = normalize_remote_workspace(config)
        if not public:
            _invalid("Remote workspace is required")
        root = _string(root, "root", required=True)
        _absolute(root)
        connection = self.get(public)
        public["root"] = connection.canonical_root(root)
        with self._lock:
            if self._connections.get(public["connection_id"]) is not connection:
                raise RemoteWorkspaceError(409, "remote_connection_changed", "Connection changed while binding the root")
            self._roots[public["connection_id"]].add(public["root"])
        return public

    def get(self, config: dict) -> RemoteConnection:
        """Accept an authorized persisted config. Draft callers must use connection_config first."""
        public = normalize_remote_workspace(config)
        if not public:
            _invalid("Remote workspace is required")
        with self._lock:
            connection = self._connections.get(public["connection_id"])
            if connection is None:
                connection = RemoteConnection(public)
                self._connections[public["connection_id"]] = connection
            elif any(connection.config[key] != public[key] for key in _IDENTITY_FIELDS):
                raise RemoteWorkspaceError(409, "remote_connection_mismatch", "Connection identity does not match its saved configuration")
            self._roots.setdefault(public["connection_id"], set()).add(public["root"])
            return connection

    def close_all(self) -> None:
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
            self._owners.clear()
            self._roots.clear()
            self._generation += 1
        for connection in connections:
            connection.close()


_service = RemoteWorkspaceService()


def get_remote_workspace_service() -> RemoteWorkspaceService:
    return _service
