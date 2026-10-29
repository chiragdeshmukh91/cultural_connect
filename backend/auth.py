"""Minimal, safe identity for self-serve individuals.

The project had no authentication. Instead of trusting a display name, each individual gets a random
256-bit bearer token when they first save a profile. Only its SHA-256 hash is stored server-side; the
browser keeps the token (localStorage) and can export it as a private "recovery key" for another device.
This is pseudonymous: there is no email/phone verification. A production deployment should swap this
module for a real identity provider; every endpoint already depends on `current_user` only.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from . import db


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(c) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    uid = "U" + uuid.uuid4().hex[:12]
    c.execute("INSERT INTO users (id, token_hash, created_at) VALUES (?,?,?)", (uid, _hash(token), time.time()))
    return uid, token


def user_from_token(token: str | None) -> str | None:
    if not token or len(token) > 200:
        return None
    with db.read() as c:
        row = c.execute("SELECT id FROM users WHERE token_hash = ?", (_hash(token),)).fetchone()
    return row["id"] if row else None


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def current_user(authorization: str | None = Header(default=None)) -> str:
    uid = user_from_token(_bearer(authorization))
    if not uid:
        raise HTTPException(401, "Sign in required: create a profile or restore it with your recovery key.")
    return uid


def optional_user(authorization: str | None = Header(default=None)) -> str | None:
    return user_from_token(_bearer(authorization))


# ---------------------------------------------------------------- rate limiting (per process)
_hits: dict[str, deque] = defaultdict(deque)
_rl_lock = threading.Lock()


def rate_limit(key: str, limit: int, window: float = 60.0):
    now = time.time()
    with _rl_lock:
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "You're doing that too often — please wait a moment and try again.")
        q.append(now)


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"
