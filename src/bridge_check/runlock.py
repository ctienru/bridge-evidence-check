"""Run lock (contract §11).

`exclusive_run_lock` takes `fcntl.flock(LOCK_EX | LOCK_NB)` on `<db>.lock` next to the
**resolved** DB path (symlinks followed) and holds it for the whole run, including the
wait on the API. The DB is not opened before the lock is held, so a second process that
cannot get the lock never touches the DB. The OS releases the lock when the holder exits
or is killed.

A symlink resolves to the real path, so it shares the lock and SQLite opens the same
file and the same `-wal` / `-shm` files. A hard link cannot be made safe by a lock:
SQLite finds the WAL by the path it was opened with, so two names of one file see
different WALs and can lose or corrupt committed data
(https://sqlite.org/howtocorrupt.html#multiple_links_to_the_same_file). The store
therefore refuses any DB file with more than one link (`store.DatabaseHasLinks`).
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RunLockHeld(Exception):
    """Another run holds the lock for this database."""


def resolve_db_path(db_path: Path | str) -> Path:
    """The canonical DB path: absolute, symlinks followed (the file may not exist yet)."""
    return Path(db_path).expanduser().resolve()


def lock_path(db_path: Path | str) -> Path:
    """The lock file next to the resolved DB path."""
    p = resolve_db_path(db_path)
    return p.with_name(p.name + ".lock")


@contextmanager
def exclusive_run_lock(db_path: Path | str, blocking: bool = False) -> Iterator[Path]:
    """Hold the run lock of `db_path`; yields the resolved DB path."""
    db = resolve_db_path(db_path)
    path = lock_path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError:
            raise RunLockHeld("another run holds the lock") from None
        try:
            yield db
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
