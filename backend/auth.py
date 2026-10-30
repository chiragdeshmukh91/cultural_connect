"""Accounts and sessions.

* Email + password accounts. Passwords are hashed with scrypt (stdlib) and a per-user salt; never stored in plaintext.
* Sessions are random 256-bit bearer tokens; only their SHA-256 hash is stored, with a sliding expiry.
* Password-reset and email-verification tokens are single-use, hashed and time-limited.
* Legacy pseudonymous users (created before accounts existed) still authenticate with their recovery key and
  can attach an email/password to the same user id ("claim"), so no data is lost.
* Rate limiting is per process (documented limitation).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from . import config, db, mailer

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
RESET_TTL = 3600
VERIFY_TTL = 3 * 24 * 3600
LOCK_AFTER = 8
LOCK_SECONDS = 15 * 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(dk) // 2)
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


def check_password_strength(pw: str):
    if len(pw) < 10:
        raise HTTPException(422, "Password must be at least 10 characters.")
    if pw.lower() == pw or pw.upper() == pw or not re.search(r"\d", pw):
        raise HTTPException(422, "Use a mix of upper- and lower-case letters and at least one number.")


def norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e) or len(e) > 254:
        raise HTTPException(422, "Enter a valid email address.")
    return e


# ---------------------------------------------------------------- users & sessions
def create_user(c) -> tuple[str, str]:
    """Bare user row (shared by accounts and legacy pseudonymous users)."""
    token = secrets.token_urlsafe(32)
    uid = "U" + uuid.uuid4().hex[:12]
    c.execute("INSERT INTO users (id, token_hash, created_at) VALUES (?,?,?)", (uid, _hash(token), time.time()))
    return uid, token


def new_session(c, uid: str) -> str:
    token = "s_" + secrets.token_urlsafe(32)
    now = time.time()
    c.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (_hash(token), uid, now, now + config.SESSION_DAYS * 86400, now))
    return token


def user_from_token(token: str | None) -> str | None:
    if not token or len(token) > 200:
        return None
    h = _hash(token)
    now = time.time()
    with db.read() as c:
        s = c.execute("SELECT user_id, expires_at, last_seen FROM sessions WHERE token_hash = ?", (h,)).fetchone()
        if s:
            if s["expires_at"] < now:
                return None
            if now - s["last_seen"] > 3600:  # sliding expiry, written at most hourly
                c.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE token_hash = ?",
                          (now, now + config.SESSION_DAYS * 86400, h))
            return s["user_id"]
        row = c.execute("SELECT id FROM users WHERE token_hash = ?", (h,)).fetchone()  # legacy recovery key
    return row["id"] if row else None


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def current_user(authorization: str | None = Header(default=None)) -> str:
    token = _bearer(authorization)
    uid = user_from_token(token)
    if not uid:
        if token and token.startswith("s_"):
            raise HTTPException(401, "Your session has expired — please sign in again.")
        raise HTTPException(401, "Please sign in to continue.")
    return uid


def optional_user(authorization: str | None = Header(default=None)) -> str | None:
    return user_from_token(_bearer(authorization))


def account_of(uid: str) -> dict | None:
    with db.read() as c:
        a = c.execute("SELECT user_id, email, email_verified, primary_mode, created_at FROM accounts WHERE user_id = ?", (uid,)).fetchone()
    return dict(a) if a else None


def is_admin(uid: str) -> bool:
    a = account_of(uid)
    return bool(a and a["email_verified"] and a["email"] in config.ADMIN_EMAILS)


# ---------------------------------------------------------------- account flows
def _issue(c, uid: str, purpose: str, ttl: int) -> str:
    tok = secrets.token_urlsafe(32)
    c.execute("INSERT INTO auth_tokens VALUES (?,?,?,?,?,NULL)", (_hash(tok), uid, purpose, time.time(), time.time() + ttl))
    return tok


def _send_verify(email: str, tok: str):
    mailer.send(email, "Confirm your Culture Connect email",
                f"Confirm your email address:\n{config.APP_BASE_URL}/#/auth/verify?token={tok}\n\nThis link expires in 3 days.")


def signup(email: str, password: str, mode: str | None) -> dict:
    email = norm_email(email)
    check_password_strength(password)
    pw = hash_password(password)
    with db.tx() as c:
        if c.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists — sign in instead.")
        uid, _ = create_user(c)
        c.execute("INSERT INTO accounts (user_id, email, password_hash, primary_mode, created_at, last_login_at) VALUES (?,?,?,?,?,?)",
                  (uid, email, pw, mode, time.time(), time.time()))
        token = new_session(c, uid)
        vt = _issue(c, uid, "verify", VERIFY_TTL)
    _send_verify(email, vt)
    return {"token": token, "user_id": uid, "email_delivery": "sent" if mailer.enabled() else "not_configured"}


def claim(uid: str, email: str, password: str) -> dict:
    """Attach email/password to an existing (legacy pseudonymous) user — keeps all their data."""
    email = norm_email(email)
    check_password_strength(password)
    pw = hash_password(password)
    with db.tx() as c:
        if c.execute("SELECT 1 FROM accounts WHERE user_id = ?", (uid,)).fetchone():
            raise HTTPException(409, "This profile already has an account.")
        if c.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "That email is already used by another account.")
        c.execute("INSERT INTO accounts (user_id, email, password_hash, primary_mode, created_at, last_login_at) VALUES (?,?,?,?,?,?)",
                  (uid, email, pw, "individual", time.time(), time.time()))
        token = new_session(c, uid)
        vt = _issue(c, uid, "verify", VERIFY_TTL)
    _send_verify(email, vt)
    return {"token": token, "user_id": uid}


def signin(email: str, password: str) -> dict:
    try:
        email = norm_email(email)
    except HTTPException:
        raise HTTPException(401, "Email or password is incorrect.")
    with db.tx() as c:
        a = c.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
        if not a:
            hash_password(password)  # equalise timing for unknown emails
            raise HTTPException(401, "Email or password is incorrect.")
        if a["locked_until"] and a["locked_until"] > time.time():
            raise HTTPException(429, "Too many failed attempts. Try again in a few minutes or reset your password.")
        if not verify_password(password, a["password_hash"]):
            fails = a["failed_attempts"] + 1
            c.execute("UPDATE accounts SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
                      (fails, time.time() + LOCK_SECONDS if fails >= LOCK_AFTER else None, a["user_id"]))
            c.execute("COMMIT"); c.execute("BEGIN")  # persist the failure counter even though we raise
            raise HTTPException(401, "Email or password is incorrect.")
        c.execute("UPDATE accounts SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE user_id = ?",
                  (time.time(), a["user_id"]))
        token = new_session(c, a["user_id"])
    return {"token": token, "user_id": a["user_id"]}


def signout(token: str | None):
    if token:
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def forgot(email: str):
    try:
        email = norm_email(email)
    except HTTPException:
        return
    with db.tx() as c:
        a = c.execute("SELECT user_id FROM accounts WHERE email = ?", (email,)).fetchone()
        if not a:
            return  # same response either way: no account enumeration
        tok = _issue(c, a["user_id"], "reset", RESET_TTL)
    mailer.send(email, "Reset your Culture Connect password",
                f"Someone asked to reset your password. If it was you, open:\n{config.APP_BASE_URL}/#/auth/reset?token={tok}\n\n"
                "This link expires in 1 hour. If you didn't ask, ignore this email.")


def _consume(c, tok: str, purpose: str) -> str:
    row = c.execute("SELECT * FROM auth_tokens WHERE token_hash = ? AND purpose = ?", (_hash(tok or ""), purpose)).fetchone()
    if not row or row["used_at"] or row["expires_at"] < time.time():
        raise HTTPException(400, "This link is invalid or has expired. Request a new one.")
    c.execute("UPDATE auth_tokens SET used_at = ? WHERE token_hash = ?", (time.time(), row["token_hash"]))
    return row["user_id"]


def reset(tok: str, password: str) -> dict:
    check_password_strength(password)
    pw = hash_password(password)
    with db.tx() as c:
        uid = _consume(c, tok, "reset")
        c.execute("UPDATE accounts SET password_hash = ?, failed_attempts = 0, locked_until = NULL, email_verified = 1 WHERE user_id = ?", (pw, uid))
        c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))  # sign out everywhere
        token = new_session(c, uid)
    return {"token": token, "user_id": uid}


def verify_email(tok: str) -> dict:
    with db.tx() as c:
        uid = _consume(c, tok, "verify")
        c.execute("UPDATE accounts SET email_verified = 1 WHERE user_id = ?", (uid,))
    return {"verified": True}


def resend_verification(uid: str):
    with db.tx() as c:
        a = c.execute("SELECT email, email_verified FROM accounts WHERE user_id = ?", (uid,)).fetchone()
        if not a or a["email_verified"]:
            return
        tok = _issue(c, uid, "verify", VERIFY_TTL)
    _send_verify(a["email"], tok)


def change_password(uid: str, current: str, new: str):
    check_password_strength(new)
    with db.tx() as c:
        a = c.execute("SELECT password_hash FROM accounts WHERE user_id = ?", (uid,)).fetchone()
        if not a or not verify_password(current, a["password_hash"]):
            raise HTTPException(401, "Current password is incorrect.")
        c.execute("UPDATE accounts SET password_hash = ? WHERE user_id = ?", (hash_password(new), uid))


def set_mode(uid: str, mode: str):
    with db.tx() as c:
        c.execute("UPDATE accounts SET primary_mode = ? WHERE user_id = ?", (mode, uid))


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


def rate_refund(key: str):
    """Give back the most recent hit (used when a request failed validation)."""
    with _rl_lock:
        q = _hits.get(key)
        if q:
            q.pop()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"
