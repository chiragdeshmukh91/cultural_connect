"""SQLite access + a tiny reversible migration runner (no ORM existed in this project; sqlite3 stdlib is reused).

Usage:
    python -m backend.db status        # list applied migrations
    python -m backend.db up            # apply pending migrations (also runs automatically at app start)
    python -m backend.db down 0002     # roll back down to (and including) migration 0002
"""
from __future__ import annotations

import contextlib
import sqlite3
import sys
import time
from pathlib import Path

from . import config

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None)  # explicit transactions only
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 10000")
    return c


@contextlib.contextmanager
def tx(immediate: bool = True):
    """Write transaction. BEGIN IMMEDIATE takes the write lock up front, so check-then-insert
    sequences (capacity, duplicate Circles, RSVPs) cannot race."""
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield c
        c.execute("COMMIT")
    except BaseException:
        with contextlib.suppress(sqlite3.Error):
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


@contextlib.contextmanager
def read():
    c = connect()
    try:
        yield c
    finally:
        c.close()


def _files(direction: str):
    return sorted(MIGRATIONS.glob(f"*.{direction}.sql"))


def _ensure_table(c):
    c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at REAL NOT NULL)")


def applied() -> list[str]:
    with read() as c:
        _ensure_table(c)
        return [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")]


def migrate() -> list[str]:
    done = set(applied())
    ran = []
    for f in _files("up"):
        version = f.name.split("_", 1)[0]
        if version in done:
            continue
        sql = f.read_text(encoding="utf-8")
        c = connect()
        try:
            c.executescript("BEGIN;\n" + sql + f"\nINSERT INTO schema_migrations VALUES ('{version}', {time.time()});\nCOMMIT;")
        except sqlite3.Error:
            with contextlib.suppress(sqlite3.Error):
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        ran.append(version)
    return ran


def rollback(to_version: str) -> list[str]:
    """Run down-migrations for every applied version >= to_version, newest first."""
    done = applied()
    ran = []
    for f in reversed(_files("down")):
        version = f.name.split("_", 1)[0]
        if version not in done or version < to_version:
            continue
        c = connect()
        try:
            c.executescript("BEGIN;\n" + f.read_text(encoding="utf-8") +
                            f"\nDELETE FROM schema_migrations WHERE version = '{version}';\nCOMMIT;")
        finally:
            c.close()
        ran.append(version)
    return ran


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "up":
        print("applied:", migrate() or "nothing pending")
    elif cmd == "down" and len(sys.argv) > 2:
        print("rolled back:", rollback(sys.argv[2]) or "nothing")
    else:
        print("applied migrations:", applied())
