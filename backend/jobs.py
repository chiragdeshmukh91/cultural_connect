"""Persistent background job queue for agent workflows (SQLite-backed, no extra infrastructure).

* A run is a row in agent_runs; every tool call it makes is a row in agent_steps (real messages, sources, errors).
* Completed step outputs are kept in agent_runs.state, so a run interrupted by a restart resumes where it stopped:
  a 'running' run whose lease expired is put back in the queue and replays only the steps that had not finished.
* dedupe_key: at most one queued/running/paused run per key (repeated triggers collapse into one run).
  once_key: the run can only ever be created once (reminders, follow-ups).
* Recoverable failures (Qloo/network errors, a locked database) are retried with exponential backoff up to
  max_attempts; anything else fails the run and the error is shown in the Agent Activity Centre.
* The worker is a daemon thread started with the app; it does not depend on any browser being open.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
import uuid
from typing import Callable

from . import db
from .qloo_client import QlooError

log = logging.getLogger("culture_connect.jobs")
LEASE_SECONDS = 300          # a 'running' run not finished within this window is considered interrupted
BACKOFF_SECONDS = 20         # retry delay: 20s, 40s, 80s ...
HANDLERS: dict[str, Callable] = {}
_worker: threading.Thread | None = None
_stop = threading.Event()
_run_lock = threading.Lock()  # one runner at a time inside this process (SQLite is single-writer anyway)


class Skip(Exception):
    """Raised by a workflow when it should stop without doing anything (e.g. consent withdrawn)."""


class Recoverable(Exception):
    """Raised by a workflow for a transient failure that should be retried."""


def now() -> float:
    return time.time()


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


# ---------------------------------------------------------------- enqueue
def enqueue(kind: str, *, subject_type: str = "", subject_id: str = "", user_id: str | None = None,
            circle_id: str | None = None, trigger: str = "", payload: dict | None = None, dedupe_key: str | None = None,
            once_key: str | None = None, delay: float = 0, max_attempts: int = 3, c=None) -> str | None:
    """Create a run (or return the existing active run for the same dedupe_key). Returns None if once_key was used."""
    def _do(cx):
        rid = "R" + uuid.uuid4().hex[:12]
        ts = now()
        cur = cx.execute("""INSERT OR IGNORE INTO agent_runs (id, kind, subject_type, subject_id, user_id, circle_id, trigger, status,
                            dedupe_key, once_key, max_attempts, next_run_at, input, created_at, updated_at)
                            VALUES (?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?)""",
                         (rid, kind, subject_type, subject_id, user_id, circle_id, trigger[:120], dedupe_key, once_key,
                          max_attempts, ts + delay, json.dumps(payload or {}), ts, ts))
        if cur.rowcount == 1:
            return rid
        if dedupe_key:
            r = cx.execute("SELECT id FROM agent_runs WHERE dedupe_key = ? AND status IN ('queued','running','paused')",
                           (dedupe_key,)).fetchone()
            if r:
                return r["id"]
        return None
    if c is not None:
        return _do(c)
    with db.tx() as cx:
        return _do(cx)


# ---------------------------------------------------------------- execution context
class Ctx:
    """Passed to workflow handlers. step() records a real tool call and makes it resumable."""

    def __init__(self, run):
        self.run = run
        self.id = run["id"]
        self.input = json.loads(run["input"] or "{}")
        self.state = json.loads(run["state"] or "{}")
        self.attempt = run["attempts"]

    def _save_state(self):
        with db.tx() as c:
            c.execute("UPDATE agent_runs SET state = ?, updated_at = ? WHERE id = ?", (json.dumps(self.state, default=str), now(), self.id))

    def done(self, name: str) -> bool:
        return name in self.state.get("_done", {})

    def out(self, name: str, default=None):
        return self.state.get("_done", {}).get(name, default)

    def step(self, name: str, tool: str, fn: Callable[[], dict]):
        """Run fn once per run. fn returns {"result": ..., "message": str, "status": ok|warn|skipped, "sources": [...]}.
        On replay after a restart, a completed step is not executed again; its stored result is returned."""
        if self.done(name):
            return self.out(name)
        with db.tx() as c:
            sid = c.execute("INSERT INTO agent_steps (run_id, attempt, name, tool, status, started_at) VALUES (?,?,?,?, 'running', ?)",
                            (self.id, self.attempt, name, tool, now())).lastrowid
        try:
            r = fn() or {}
        except Exception as exc:
            skipped = isinstance(exc, Skip)
            msg = str(exc) if skipped else _err(exc)
            with db.tx() as c:
                c.execute("UPDATE agent_steps SET status = ?, message = ?, finished_at = ? WHERE id = ?",
                          ("skipped" if skipped else "error", msg[:1000], now(), sid))
            raise
        with db.tx() as c:
            c.execute("UPDATE agent_steps SET status = ?, message = ?, sources = ?, data = ?, finished_at = ? WHERE id = ?",
                      (r.get("status", "ok"), str(r.get("message", ""))[:1000], json.dumps(r.get("sources", []), default=str),
                       json.dumps(r.get("data", {}), default=str)[:20000], now(), sid))
        self.state.setdefault("_done", {})[name] = r.get("result")
        self._save_state()
        return r.get("result")


def _err(exc: BaseException) -> str:
    if isinstance(exc, QlooError):
        return f"Qloo request failed ({exc.status or 'network error'}): {exc}"
    detail = getattr(exc, "detail", None)
    if detail is not None:
        return detail if isinstance(detail, str) else json.dumps(detail, default=str)
    return f"{type(exc).__name__}: {exc}"


def _recoverable(exc: BaseException) -> bool:
    if isinstance(exc, Recoverable):
        return True
    if isinstance(exc, QlooError):
        return exc.status in (None, 408, 429) or (isinstance(exc.status, int) and exc.status >= 500)
    return isinstance(exc, sqlite3.OperationalError)


# ---------------------------------------------------------------- claim / run
def _claim():
    with db.tx() as c:
        c.execute("UPDATE agent_runs SET status = 'queued', locked_at = NULL, updated_at = ? "
                  "WHERE status = 'running' AND locked_at < ?", (now(), now() - LEASE_SECONDS))  # resume interrupted runs
        r = c.execute("SELECT * FROM agent_runs WHERE status = 'queued' AND next_run_at <= ? ORDER BY next_run_at, created_at LIMIT 1",
                      (now(),)).fetchone()
        if not r:
            return None
        c.execute("UPDATE agent_runs SET status = 'running', locked_at = ?, attempts = attempts + 1, "
                  "started_at = COALESCE(started_at, ?), updated_at = ? WHERE id = ?", (now(), now(), now(), r["id"]))
        return c.execute("SELECT * FROM agent_runs WHERE id = ?", (r["id"],)).fetchone()


def _finish(rid: str, status: str, output=None, error: str = "", retry_in: float | None = None):
    with db.tx() as c:
        cur = c.execute("SELECT status FROM agent_runs WHERE id = ?", (rid,)).fetchone()
        if cur and cur["status"] in ("paused", "cancelled"):  # user paused/cancelled while it ran: keep their decision
            c.execute("UPDATE agent_runs SET locked_at = NULL, error = ?, updated_at = ? WHERE id = ?", (error, now(), rid))
            return
        if retry_in is not None:
            c.execute("UPDATE agent_runs SET status = 'queued', locked_at = NULL, next_run_at = ?, error = ?, updated_at = ? WHERE id = ?",
                      (now() + retry_in, error, now(), rid))
        else:
            c.execute("UPDATE agent_runs SET status = ?, locked_at = NULL, output = ?, error = ?, finished_at = ?, updated_at = ? WHERE id = ?",
                      (status, json.dumps(output or {}, default=str), error, now(), now(), rid))


def run_one(run) -> str:
    fn = HANDLERS.get(run["kind"])
    if not fn:
        _finish(run["id"], "failed", error=f"No handler for '{run['kind']}'")
        return "failed"
    ctx = Ctx(run)
    try:
        out = fn(ctx)
    except Skip as s:
        _finish(run["id"], "skipped", {"reason": str(s)}, error="")
        return "skipped"
    except Exception as exc:  # noqa: BLE001 — every failure is recorded, nothing is swallowed silently
        msg = _err(exc)
        if _recoverable(exc) and run["attempts"] < run["max_attempts"]:
            delay = BACKOFF_SECONDS * (2 ** (run["attempts"] - 1))
            _finish(run["id"], "queued", error=f"Attempt {run['attempts']} failed, retrying in {int(delay)}s: {msg}", retry_in=delay)
            return "retry"
        log.warning("agent run %s failed: %s\n%s", run["id"], msg, traceback.format_exc())
        _finish(run["id"], "failed", error=msg)
        return "failed"
    _finish(run["id"], "succeeded", out)
    return "succeeded"


def run_pending(limit: int = 50) -> int:
    """Run every due job (used by the worker loop, and synchronously by tests)."""
    n = 0
    with _run_lock:
        while n < limit:
            r = _claim()
            if not r:
                break
            run_one(r)
            n += 1
    return n


# ---------------------------------------------------------------- user controls
def get_run(rid: str):
    with db.read() as c:
        return c.execute("SELECT * FROM agent_runs WHERE id = ?", (rid,)).fetchone()


def control(rid: str, action: str) -> str:
    with db.tx() as c:
        r = c.execute("SELECT status FROM agent_runs WHERE id = ?", (rid,)).fetchone()
        st = r["status"]
        if action == "pause" and st in ("queued", "running"):
            new = "paused"
        elif action == "resume" and st == "paused":
            new = "queued"
        elif action == "retry" and st in ("failed", "skipped"):
            c.execute("UPDATE agent_runs SET attempts = 0 WHERE id = ?", (rid,))
            new = "queued"
        elif action == "cancel" and st in ("queued", "paused", "failed"):
            new = "cancelled"
        else:
            raise ValueError(f"Can't {action} a run that is {st}.")
        try:
            c.execute("UPDATE agent_runs SET status = ?, next_run_at = ?, updated_at = ? WHERE id = ?", (new, now(), now(), rid))
        except sqlite3.IntegrityError:
            raise ValueError("Another run for the same task is already queued.")
        return new


# ---------------------------------------------------------------- worker thread
def start_worker(tick: Callable[[], None] | None = None, interval: float = 2.0, tick_every: float = 30.0):
    """Background loop: run due jobs every `interval` s and call tick() (the coordination sweep) every `tick_every` s."""
    global _worker
    if _worker and _worker.is_alive():
        return
    _stop.clear()

    def loop():
        last = 0.0
        while not _stop.is_set():
            try:
                if tick and now() - last >= tick_every:
                    last = now()
                    tick()
                run_pending()
            except Exception:  # noqa: BLE001 — keep the worker alive; failures are logged
                log.exception("agent worker loop error")
            _stop.wait(interval)

    _worker = threading.Thread(target=loop, name="agent-worker", daemon=True)
    _worker.start()


def stop_worker():
    _stop.set()
