"""No-replace directory publication and exclusive Windows workspace moves."""

from __future__ import annotations

import ctypes
import os
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path

from scripts import _pytest_history_inventory as inv


def publish(source: Path, target: Path) -> None:
    source = inv.plain_path(source)
    target = inv.plain_path(target)
    if os.path.lexists(target):
        raise FileExistsError(f"restore or move conflict: {target}")
    if os.name == "nt":
        source.rename(target)  # MoveFileExW without REPLACE_EXISTING.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    elif sys.platform == "darwin":
        result = libc.renamex_np(os.fsencode(source), os.fsencode(target), 4)  # RENAME_EXCL
    else:
        raise inv.Review("atomic no-replace rename is unavailable on this platform")
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


if os.name == "nt":
    import _winapi
    import msvcrt
    from ctypes import wintypes

    _OPEN_REPARSE_POINT = 0x00200000
    _BACKUP_SEMANTICS = 0x02000000
    _DELETE = 0x10000
    _READ_ATTRIBUTES = 0x80

    class _RenameInfo(ctypes.Structure):
        _fields_ = [("ReplaceIfExists", wintypes.BOOLEAN), ("RootDirectory", wintypes.HANDLE),
                    ("FileNameLength", wintypes.DWORD), ("FileName", wintypes.WCHAR * 1)]

    _rename = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    _rename.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _rename.restype = wintypes.BOOL

    def _directory(path, access, share):
        return _winapi.CreateFile(str(path), access, share, 0, _winapi.OPEN_EXISTING,
                                  _BACKUP_SEMANTICS | _OPEN_REPARSE_POINT, 0)

    def _rename_handle(handle, destination):
        name = str(destination).encode("utf-16-le")
        buffer = ctypes.create_string_buffer(ctypes.sizeof(_RenameInfo) + len(name))
        info = _RenameInfo.from_buffer(buffer)
        info.FileNameLength = len(name)
        ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.FileName.offset, name, len(name))
        if not _rename(handle, 3, buffer, len(buffer)):  # FileRenameInfo, ReplaceIfExists = FALSE
            raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def reader(path, *, exclusive=False):
    if os.name == "nt":
        handle = _winapi.CreateFile(str(path), _winapi.GENERIC_READ, 0 if exclusive else 1,
                                    0, _winapi.OPEN_EXISTING, _OPEN_REPARSE_POINT, 0)
        stream = os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb")
    else:
        stream = path.open("rb")
    with stream:
        info = os.fstat(stream.fileno())
        inv.reject_link(info, path)
        if exclusive and info.st_nlink != 1:
            raise inv.Review(f"file has multiple links: {path}")
        yield stream


@contextmanager
def pin_parent(path):
    if os.name != "nt":
        yield
        return
    # Allow normal access to descendants, hold this directory against replacement.
    handle = _directory(inv.plain_path(path), _READ_ATTRIBUTES, 3)
    try:
        inv.plain_path(path)
        yield
    finally:
        _winapi.CloseHandle(handle)


def detach_workspace(source, target, files, check_owners):
    if os.name != "nt":
        raise inv.Review("exclusive workspace detach requires Windows")
    if os.path.lexists(target):
        raise FileExistsError(f"quarantine conflict: {target}")
    inv.check_tree(source, files)
    with ExitStack() as directory:
        handle = _directory(source, _DELETE | _READ_ATTRIBUTES, 0)
        directory.callback(_winapi.CloseHandle, handle)
        with ExitStack() as children:
            for name, expected in files.items():
                path = source / name
                if name.endswith("/"):
                    child = _directory(path, _READ_ATTRIBUTES, 0)
                    children.callback(_winapi.CloseHandle, child)
                    continue
                stream = children.enter_context(reader(path, exclusive=True))
                info = os.fstat(stream.fileno())
                if (info.st_size != expected["size"] or info.st_mtime_ns != expected["mtime_ns"]
                        or inv.digest(stream) != expected["sha256"]):
                    raise inv.Review(f"source content changed: {path}")
            check_owners()
        # Windows requires descendant handles closed to rename a directory.
        # Keep the exclusive directory handle through the no-replace rename.
        _rename_handle(handle, target)
    try:
        inv.check_tree(target, files, hashes=True)
        check_owners()
    except inv.READ_ERRORS:
        # A just-closed writer could have changed a descendant at the rename
        # boundary. Put its directory back, preserving a concurrently created target.
        publish(target, source)
        raise
