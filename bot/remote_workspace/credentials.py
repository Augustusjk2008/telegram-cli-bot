"""Encrypted, connection-bound SSH passwords under the active application data root."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from cryptography.fernet import Fernet, InvalidToken

from bot.runtime_paths import get_app_data_root


SSH_IDENTITY_FIELDS = ("host", "port", "username", "host_key_fingerprint", "key_filename", "platform")


def _identity(config: dict) -> dict:
    return {
        "connection_id": config["connection_id"],
        **{field: config.get(field, "posix" if field == "platform" else "") for field in SSH_IDENTITY_FIELDS},
    }


class SSHCredentialStore:
    """Only callers holding an authorized, verified configuration may retrieve a password."""

    def __init__(self, root: str | Path | None = None):
        self._root_override = Path(root) if root is not None else None
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root_override or get_app_data_root() / "remote-ssh"

    @staticmethod
    def _path(root: Path, config: dict) -> Path:
        digest = hashlib.sha256(config["connection_id"].encode("utf-8")).hexdigest()
        return root / "credentials" / f"{digest}.enc"

    @staticmethod
    def _key(root: Path, *, create: bool = False) -> bytes:
        path = root / "secret.key"
        try:
            return path.read_bytes().strip()
        except FileNotFoundError:
            if not create:
                raise
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = Fernet.generate_key()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            return path.read_bytes().strip()
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        return key

    def get(self, config: dict) -> str | None:
        with self._lock:
            root = self.root
            try:
                encrypted = self._path(root, config).read_bytes()
                raw = Fernet(self._key(root)).decrypt(encrypted)
                payload = json.loads(raw)
            except (OSError, InvalidToken, ValueError, UnicodeError):
                return None
            if not isinstance(payload, dict) or payload.get("identity") != _identity(config):
                return None
            password = payload.get("password")
            return password if isinstance(password, str) and password else None

    def save(self, config: dict, password: str) -> None:
        with self._lock:
            root = self.root
            path = self._path(root, config)
            payload = {"identity": _identity(config), "password": password}
            encrypted = Fernet(self._key(root, create=True)).encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encrypted)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise

    def delete(self, config: dict) -> None:
        with self._lock:
            try:
                self._path(self.root, config).unlink()
            except FileNotFoundError:
                pass
