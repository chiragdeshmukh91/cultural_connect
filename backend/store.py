"""Tiny SQLite document store for programs (synthetic demo data only)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

from . import config

_lock = threading.Lock()


def _conn():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS programs (id TEXT PRIMARY KEY, doc TEXT NOT NULL, updated REAL)")
    return c


def list_programs():
    with _lock, _conn() as c:
        rows = c.execute("SELECT id, doc, updated FROM programs ORDER BY updated DESC").fetchall()
    out = []
    for pid, doc, upd in rows:
        d = json.loads(doc)
        out.append({"id": pid, "name": d.get("name"), "participants": len(d.get("participants", [])), "updated": upd})
    return out


def get(pid: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT doc FROM programs WHERE id=?", (pid,)).fetchone()
    return json.loads(row[0]) if row else None


def save(doc: dict) -> dict:
    doc.setdefault("id", "P" + uuid.uuid4().hex[:8])
    doc["updated"] = time.time()
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO programs (id, doc, updated) VALUES (?,?,?)",
                  (doc["id"], json.dumps(doc, default=str), doc["updated"]))
    return doc


def delete(pid: str):
    with _lock, _conn() as c:
        c.execute("DELETE FROM programs WHERE id=?", (pid,))
