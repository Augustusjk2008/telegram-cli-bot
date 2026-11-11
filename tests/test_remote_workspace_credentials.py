from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

from bot.remote_workspace import credentials


CONFIG = {
    "connection_id": "connection-1", "host": "host.test", "port": 22, "username": "dev",
    "host_key_fingerprint": "SHA256:" + "A" * 43, "key_filename": "", "root": "/project",
}


def test_password_is_encrypted_and_bound_to_verified_identity(tmp_path):
    store = credentials.SSHCredentialStore(tmp_path)
    store.save(CONFIG, "password-机密")
    encrypted = next((tmp_path / "credentials").glob("*.enc"))
    assert b"password" not in encrypted.read_bytes()
    assert credentials.SSHCredentialStore(tmp_path).get(CONFIG) == "password-机密"
    assert store.get({**CONFIG, "root": "/another-root", "platform": "posix"}) == "password-机密"
    for field, changed in {
        "host": "other.test", "port": 2222, "username": "other", "host_key_fingerprint": "SHA256:" + "B" * 43,
        "key_filename": "/other-key", "platform": "windows",
    }.items():
        assert store.get({**CONFIG, field: changed}) is None, field

    other = {**CONFIG, "connection_id": "connection-2"}
    assert store.get(other) is None
    store._path(tmp_path, other).write_bytes(encrypted.read_bytes())
    assert store.get(other) is None  # Even copied ciphertext remains connection-bound.
    if os.name != "nt":
        assert encrypted.stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "secret.key").stat().st_mode & 0o777 == 0o600


def test_store_tracks_runtime_root_and_corruption_does_not_recreate_key(tmp_path, monkeypatch):
    current = tmp_path / "first"
    monkeypatch.setattr(credentials, "get_app_data_root", lambda: current)
    store = credentials.SSHCredentialStore()
    assert store.get(CONFIG) is None
    assert not current.exists()
    store.save(CONFIG, "first-password")
    first_root = store.root
    current = tmp_path / "second"
    assert store.get(CONFIG) is None
    store.save(CONFIG, "second-password")
    assert credentials.SSHCredentialStore(first_root).get(CONFIG) == "first-password"
    assert store.get(CONFIG) == "second-password"

    (store.root / "secret.key").unlink()
    assert store.get(CONFIG) is None
    assert not (store.root / "secret.key").exists()
    (store.root / "secret.key").write_bytes(b"invalid-key")
    assert store.get(CONFIG) is None


def test_failed_atomic_save_preserves_previous_password(tmp_path, monkeypatch):
    store = credentials.SSHCredentialStore(tmp_path)
    store.save(CONFIG, "original")
    monkeypatch.setattr(credentials.os, "replace", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError):
        store.save(CONFIG, "replacement")
    assert store.get(CONFIG) == "original"
    assert not list((tmp_path / "credentials").glob("*.tmp"))
    store.delete(CONFIG)
    assert store.get(CONFIG) is None
